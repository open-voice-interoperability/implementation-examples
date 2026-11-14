import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.allergy_sentinel.allergy_sentinel_agent import (
    AllergySentinelAgent,
    find_allergens,
    parse_restrictions,
)

SENTINEL_URL = "http://127.0.0.1:8307/"
MENU_DESIGNER_URL = "http://127.0.0.1:8301/"
CONVENER_URL = "http://127.0.0.1:8300/"
RECIPE_URL = "http://127.0.0.1:8303/"
SHOPPING_URL = "http://127.0.0.1:8310/"
HUMAN_URI = "openFloor://localhost:8090/CafeteriaOpsLineCheck"


def allergens_in(text):
    return {allergen for allergen, _, _ in find_allergens(text)}


class ParseRestrictionsTests(unittest.TestCase):
    def test_nut_free_rules_out_peanuts_and_tree_nuts(self):
        self.assertEqual(parse_restrictions("Plan a nut-free week"), {"peanut", "tree_nut"})

    def test_several_phrasings(self):
        text = "No shellfish please, one guest is allergic to sesame and we avoid soy"
        self.assertEqual(parse_restrictions(text), {"shellfish", "sesame", "soy"})

    def test_gluten_dairy_and_celiac(self):
        self.assertEqual(parse_restrictions("gluten-free and dairy free"), {"wheat", "milk"})
        self.assertEqual(parse_restrictions("celiac-safe options"), {"wheat"})

    def test_plain_request_has_no_restrictions(self):
        self.assertEqual(parse_restrictions("Plan five days of lunches for 450"), set())


class FindAllergensTests(unittest.TestCase):
    def test_ingredients_and_near_certain_dishes(self):
        self.assertEqual(allergens_in("Thai chicken satay"), {"peanut"})
        self.assertEqual(allergens_in("Pesto"), {"tree_nut"})
        self.assertEqual(allergens_in("Falafel with tahini"), {"sesame"})
        self.assertEqual(allergens_in("Shrimp tacos"), {"shellfish"})

    def test_substitutes_and_lookalikes_are_not_flagged(self):
        self.assertEqual(allergens_in("coconut milk curry"), set())
        self.assertEqual(allergens_in("nut-free pesto"), set())
        self.assertEqual(allergens_in("dairy-free cheese"), set())
        self.assertEqual(allergens_in("cream of tartar"), set())
        self.assertEqual(allergens_in("butternut squash soup"), set())
        self.assertEqual(allergens_in("corn tortillas"), set())
        self.assertEqual(allergens_in("nutmeg and coconut"), set())

    def test_peanut_butter_is_peanut_not_dairy(self):
        self.assertEqual(allergens_in("peanut butter cookies"), {"peanut"})

    def test_item_is_the_clause_with_its_line_label(self):
        findings = find_allergens("Friday: Grilled salmon with lemon butter, peanut butter cookies")
        items = {(allergen, item) for allergen, _, item in findings}
        self.assertIn(("peanut", "Friday: peanut butter cookies"), items)
        self.assertIn(("milk", "Friday: Grilled salmon with lemon butter"), items)


class BuildAlertTests(unittest.TestCase):
    def setUp(self):
        self.agent = AllergySentinelAgent()

    def _watch(self, request=""):
        return {"restrictions": parse_restrictions(request), "reported": []}

    def test_silent_when_only_ordinary_allergens_and_no_restriction(self):
        self.assertEqual(self.agent._build_alert("Monday: Penne with tomato sauce and parmesan", self._watch()), "")

    def test_severe_allergen_flagged_without_any_restriction(self):
        alert = self.agent._build_alert("Thursday: Shrimp tacos", self._watch())
        self.assertIn("severe allergens", alert)
        self.assertIn("Shellfish: Thursday: Shrimp tacos (shrimp)", alert)

    def test_restriction_conflict_is_flagged(self):
        alert = self.agent._build_alert("Monday: Penne with parmesan", self._watch("Plan a dairy-free week"))
        self.assertIn("conflict with the request", alert)
        self.assertIn("Milk/dairy: Monday: Penne with parmesan (parmesan)", alert)

    def test_each_item_is_reported_only_once(self):
        watch = self._watch()
        self.assertTrue(self.agent._build_alert("Tuesday: Pesto pasta", watch))
        self.assertEqual(self.agent._build_alert("Tuesday: Pesto pasta", watch), "")


class EnvelopeTests(unittest.TestCase):
    """End to end through handle_json_envelope, the way the floor manager
    delivers events."""

    def setUp(self):
        self.agent = AllergySentinelAgent()

    def _send(self, events, conversants=(SENTINEL_URL, MENU_DESIGNER_URL, CONVENER_URL, RECIPE_URL, SHOPPING_URL)):
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "conv-allergy", "conversants": [
                {"identification": {"speakerUri": url, "serviceUrl": url, "conversationalName": "", "organization": "", "synopsis": ""}}
                for url in conversants
            ]},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": events,
        }}
        out = json.loads(self.agent.handle_json_envelope(json.dumps(envelope)))
        return out["openFloor"].get("events") or []

    @staticmethod
    def _utterance(speaker_uri, text):
        return {"eventType": "utterance", "parameters": {"dialogEvent": {
            "speakerUri": speaker_uri, "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": text}]}}}}}

    @staticmethod
    def _texts(events):
        return [e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                for e in events if e.get("eventType") == "utterance"]

    def test_invite_is_accepted_with_a_short_greeting(self):
        events = self._send([{"eventType": "invite", "to": {"serviceUrl": SENTINEL_URL}}])
        self.assertIn("acceptInvite", [e["eventType"] for e in events])
        self.assertIn("Allergy Sentinel on watch", self._texts(events)[0])

    TO_ME = {"speakerUri": SENTINEL_URL, "serviceUrl": SENTINEL_URL}

    def _grant(self):
        return self._send([{"eventType": "grantFloor", "to": self.TO_ME}])

    def _revoke(self):
        return self._send([{"eventType": "revokeFloor", "to": self.TO_ME, "reason": "declined: no reason given"}])

    def test_request_is_never_flagged_but_its_restrictions_are_remembered(self):
        events = self._send([self._utterance(HUMAN_URI, "Plan a nut-free week, no shrimp")])
        self.assertEqual(events, [])

        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Pesto pasta salad")])
        alert = self._texts(self._grant())[0]
        self.assertIn("conflict with the request", alert)
        self.assertIn("Tree nuts: Monday: Pesto pasta salad (pesto)", alert)

    def test_a_finding_is_held_and_the_floor_requested_with_a_reason(self):
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])

        self.assertEqual([e["eventType"] for e in events], ["requestFloor"])  # no utterance yet
        request = events[0]
        self.assertTrue(request["reason"].startswith("@issueDetected "), request["reason"])
        self.assertIn("severe allergens", request["reason"])  # and a description
        self.assertEqual(request["to"]["speakerUri"], SENTINEL_URL)  # who the floor is for

    def test_grant_releases_the_held_alert(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        events = self._grant()
        self.assertEqual([e["eventType"] for e in events], ["utterance"])
        self.assertIn("Shellfish: Thursday: Shrimp tacos (shrimp)", self._texts(events)[0])
        self.assertEqual(self._grant(), [])  # nothing left to say

    def test_the_alert_has_an_html_version_with_the_ingredient_in_bold(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos & slaw")])
        features = self._grant()[0]["parameters"]["dialogEvent"]["features"]
        html = features["html"]["tokens"][0]["value"]
        self.assertEqual(features["html"]["mimeType"], "text/html")
        self.assertIn("<b>Shrimp</b> tacos &amp; slaw (<b>shrimp</b>)", html)  # escaped, and every mention
        self.assertNotIn("<b>", features["text"]["tokens"][0]["value"])  # the text stays plain

    def test_the_allergen_group_label_is_not_bold(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Tuesday: Peanut satay noodles")])
        html = self._grant()[0]["parameters"]["dialogEvent"]["features"]["html"]["tokens"][0]["value"]
        self.assertIn("<br>Peanuts: Tuesday: <b>Peanut</b> satay noodles (<b>peanut</b>)", html)

    def test_the_greeting_has_no_html(self):
        events = self._send([{"eventType": "invite", "to": {"serviceUrl": SENTINEL_URL}}])
        utterance = [e for e in events if e["eventType"] == "utterance"][0]
        self.assertNotIn("html", utterance["parameters"]["dialogEvent"]["features"])

    def test_findings_while_waiting_join_one_request_and_one_alert(self):
        first = self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        second = self._send([self._utterance(MENU_DESIGNER_URL, "Wednesday: Falafel with tahini")])
        self.assertEqual([e["eventType"] for e in first], ["requestFloor"])
        self.assertEqual(second, [])  # already asked

        alert = self._texts(self._grant())[0]
        self.assertIn("Shrimp tacos", alert)
        self.assertIn("Falafel with tahini", alert)

    def test_revoke_while_waiting_drops_the_held_alert(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        self.assertEqual(self._revoke(), [])
        self.assertEqual(self._grant(), [])  # the convener disagreed; nothing is said

    def test_routine_revoke_does_not_cancel_a_waiting_request(self):
        # e.g. the revoke after it has spoken arriving while a newer request
        # is still outstanding -- only a "declined" revoke drops findings
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        self.assertEqual(self._send([{"eventType": "revokeFloor", "to": self.TO_ME}]), [])
        self.assertIn("Shrimp tacos", self._texts(self._grant())[0])

    def test_after_a_decision_a_new_finding_asks_again(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        self._revoke()
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Tuesday: Pesto pasta")])
        self.assertEqual([e["eventType"] for e in events], ["requestFloor"])

    def test_another_sentinels_alert_is_not_rechecked(self):
        # The Recall Sentinel's alert quotes the dish ("... with Romaine and
        # Pesto"); that must not raise a second allergy alert.
        recall_alert = ('Food recall alert: active FDA recalls involve ingredients on this menu.\n'
                        'Romaine -- on the menu in "Grilled Chicken with Romaine and Pesto":')
        self.assertEqual(self._send([self._utterance("http://127.0.0.1:8308/", recall_alert)]), [])

    def test_a_keyword_is_listed_once_per_alert(self):
        recipe = "Grilled Chicken with Pesto:\n15g pesto\nTop the chicken with the pesto."
        self._send([self._utterance(MENU_DESIGNER_URL, recipe)])
        alert = self._texts(self._grant())[0]
        self.assertEqual(alert.count("(pesto)"), 1)

    def test_the_same_ingredient_in_a_recipe_is_not_reported_again(self):
        # Live: the menu's "Shrimp and vegetable pad Thai" and its recipe's
        # wording of the shrimp raised two shellfish alerts.
        self._send([self._utterance(MENU_DESIGNER_URL, "Day 4: Shrimp and vegetable pad Thai")])
        self._grant()
        recipe = "Shrimp and vegetable pad Thai: 100g shrimp, 10g peanuts, rice noodles"
        self.assertEqual([e["eventType"] for e in self._send([self._utterance(RECIPE_URL, recipe)])], ["requestFloor"])
        alert = self._texts(self._grant())[0]
        self.assertIn("Peanuts", alert)       # new in the recipe: reported
        self.assertNotIn("Shellfish", alert)  # already reported from the menu

    def test_the_same_dish_in_other_words_is_not_reported_again(self):
        # Live: "satay" on the menu, then "peanut" in the dish's recipe.
        self._send([self._utterance(MENU_DESIGNER_URL, "Day 5: Chicken Satay with peanut sauce")])
        self._grant()
        self.assertEqual(self._send([self._utterance(RECIPE_URL, "Chicken Satay: 15ml peanut sauce, 100g chicken")]), [])

    def test_a_new_dish_with_an_allergen_already_reported_is_still_reported(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Day 2: Grilled lamb chops with tahini sauce")])
        self._grant()
        events = self._send([self._utterance(RECIPE_URL, "Vegetarian Pad Thai: 1 tbsp roasted sesame oil")])
        self.assertEqual([e["eventType"] for e in events], ["requestFloor"])
        self.assertIn("Vegetarian Pad Thai", self._texts(self._grant())[0])

    def test_other_agents_discussing_the_menu_are_not_checked(self):
        self.assertEqual(self._send([self._utterance(SHOPPING_URL, "Seafood: shrimp 45 kg")]), [])

    def test_a_new_menu_is_checked_afresh(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos")])
        self._grant()
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Thursday: Shrimp tacos with slaw")])
        self.assertEqual([e["eventType"] for e in events], ["requestFloor"])

    def test_silent_reply_when_nothing_to_flag(self):
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Grilled chicken with rice")])
        self.assertEqual(events, [])

    def test_ignores_its_own_utterances(self):
        events = self._send([self._utterance(SENTINEL_URL, "Peanuts: satay")])
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
