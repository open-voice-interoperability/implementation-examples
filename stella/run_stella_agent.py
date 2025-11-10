import json
from openfloor.envelope import Envelope, Conversation, Sender, Payload
from openfloor.events import InviteEvent, UtteranceEvent
from openfloor.dialog_event import DialogEvent, TextFeature
from stella_agent import load_manifest_from_config, StellaAgent


def make_sample_envelope(manifest):
    conv = Conversation(id="conv:sample123")
    sender = Sender(speakerUri="urn:user:alice", serviceUrl="https://example.org")

    # Create an invite and a subsequent user utterance
    invite = InviteEvent()
    user_dialog = DialogEvent(speakerUri="urn:user:alice", features={"text": TextFeature(values=["Tell me about NASA's astronomy picture of the day"])})
    utter = UtteranceEvent(dialogEvent=user_dialog)

    env = Envelope(conversation=conv, sender=sender)
    env.events.append(invite)
    env.events.append(utter)
    return env


def main():
    manifest = load_manifest_from_config()
    agent = StellaAgent(manifest)

    env = make_sample_envelope(manifest)
    out_env = agent.process_envelope(env)

    print(out_env.to_json(as_payload=True))


if __name__ == "__main__":
    main()
