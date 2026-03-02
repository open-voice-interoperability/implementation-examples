from typing import Optional, List, Tuple, Dict
from . import events as events_module
from abc import ABC, abstractmethod
from openfloor import Parameters, DialogEvent, TextFeature, To, Sender, Manifest, Conversation, Envelope, Event, InviteEvent, UtteranceEvent, ContextEvent, UninviteEvent, DeclineInviteEvent, ByeEvent, GetManifestsEvent, PublishManifestsEvent, RequestFloorEvent, GrantFloorEvent, RevokeFloorEvent
from urllib.parse import urlparse

class _EventDispatcher:
    """Simple event dispatcher that supports `+=` to add handlers and calling to invoke."""

    def __init__(self):
        self._handlers = []

    def __iadd__(self, handler):
        self._handlers.append(handler)
        return self

    def __call__(self, *args, **kwargs):
        for h in list(self._handlers):
            h(*args, **kwargs)


class OpenFloorEvents:
    """Base class for Open Floor agents that defines event handlers"""
    __events__ = (
        'on_envelope',
        'on_utterance',
        'on_context',
        'on_invite',
        'on_uninvite',
        'on_decline_invite',
        'on_bye',
        'on_get_manifests',
        'on_publish_manifests',
        'on_request_floor',
        'on_grant_floor',
        'on_revoke_floor',
        "on_yield_floor"
    )

    def __init__(self):
        for ev in self.__events__:
            setattr(self, ev, _EventDispatcher())

class OpenFloorAgent(OpenFloorEvents):

    _manifest: Optional[Manifest] = None

    def __init__(self, manifest: Manifest):
        super().__init__()
        self._manifest = manifest

    @property
    def speakerUri(self) -> str:
        return self._manifest.identification.speakerUri

    @property
    def serviceUrl(self) -> str:
        return self._manifest.identification.serviceUrl

    def add_metadata(self, events: List[Event]) -> List[Tuple[Event, Dict[str, bool]]]:
        result = []
        def normalize_uri(value: Optional[str]) -> Optional[str]:
            if not value:
                return value
            if value.startswith("agent:"):
                value = value[len("agent:"):]
            return value.rstrip("/")
        for event in events:
            addressed = False
            try:
                to = getattr(event, 'to', None)
                if to is None:
                    addressed = True
                else:
                    target_speaker = normalize_uri(getattr(to, 'speakerUri', None))
                    manifest_speaker = normalize_uri(self._manifest.identification.speakerUri)
                    target_service = normalize_uri(getattr(to, 'serviceUrl', None))
                    manifest_service = normalize_uri(self._manifest.identification.serviceUrl)

                    if target_speaker:
                        addressed = target_speaker == manifest_speaker
                    else:
                        if target_service and manifest_service:
                            if target_service == manifest_service:
                                addressed = True
                            elif target_service.rstrip('/') == manifest_service.rstrip('/'):
                                addressed = True
                            else:
                                try:
                                    parsed_target = urlparse(target_service)
                                    parsed_manifest = urlparse(manifest_service)
                                    if (
                                        parsed_target.hostname
                                        and parsed_manifest.hostname
                                        and parsed_target.hostname == parsed_manifest.hostname
                                        and (parsed_target.port or 80) == (parsed_manifest.port or 80)
                                    ):
                                        addressed = True
                                except Exception:
                                    addressed = False
            except Exception:
                addressed = False

            result.append((event, {"addressed_to_me": addressed}))
            print(f"Event {event.eventType} addressed to me: {addressed}", flush=True)

        return result

class BotAgent(OpenFloorAgent):
    _current_context: List[ContextEvent] = []
    _active_conversation: Optional[Conversation] = None
    _has_floor: bool = False

    def __init__(self, manifest: Manifest):
        super().__init__(manifest)
        self._active_conversation = None
        self._has_floor = False
        self._current_context = []
        self.__attach_handlers__()

    def __attach_handlers__(self):
        self.on_envelope += self.bot_on_envelope
        self.on_invite += self.bot_on_invite
        self.on_utterance += self.bot_on_utterance
        self.on_context += self.bot_on_context
        self.on_uninvite += self.bot_on_uninvite
        self.on_grant_floor += self.bot_on_grant_floor
        self.on_revoke_floor += self.bot_on_revoke_floor
        self.on_get_manifests += self.bot_on_get_manifests
        print(f"registered handlers: {len(self.__events__)}")

        self._event_type_to_handler = {
            "invite": self.on_invite,
            "utterance": self.on_utterance,
            "context": self.on_context,
            "uninvite": self.on_uninvite,
            "declineInvite": self.on_decline_invite,
            "bye": self.on_bye,
            "getManifests": self.on_get_manifests,
            "publishManifests": self.on_publish_manifests,
            "requestFloor": self.on_request_floor,
            "grantFloor": self.on_grant_floor,
            "revokeFloor": self.on_revoke_floor,
            "yieldFloor": self.on_yield_floor
        }

    def process_envelope(self, in_envelope: Envelope) -> Envelope:
        out_envelope = Envelope(
            conversation=in_envelope.conversation,
            sender=Sender(
                speakerUri=self.speakerUri,
                serviceUrl=self.serviceUrl
            )
        )

        self.on_envelope(in_envelope, out_envelope)
        return out_envelope

    def bot_on_envelope(self, in_envelope: Envelope, out_envelope: Envelope) -> Envelope:
        print("Entering bot_on_envelope")
        print("incoming events " + str(in_envelope.events))
        self._current_context = []

        events_with_metadata = self.add_metadata(in_envelope.events)
        my_events_with_metadata = [[event, metadata] for event, metadata in events_with_metadata if metadata["addressed_to_me"]]

        for event, metadata in my_events_with_metadata:
            print(f"Processing event: {event.to_json()}")
            print(f"Processing event with type: {event.eventType}")

            handler = self._event_type_to_handler.get(event.eventType)
            if handler is None:
                raise ValueError(f"Unknown event type: {event.eventType}")
            handler(event, in_envelope, out_envelope)

        print(f"out_envelope: {out_envelope.to_json()}")

        return out_envelope

    def bot_on_invite(self, event: InviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_invite")
        self._active_conversation = Conversation(id=in_envelope.conversation.id)

        self.bot_on_grant_floor(
            GrantFloorEvent(
                to=To(speakerUri=self._manifest.identification.speakerUri),
                reason="Automatic floor grant as a result of the invitation"
            ),
            in_envelope,
            out_envelope
        )

    def bot_on_grant_floor(self, event: GrantFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_grant_floor")
        self._has_floor = True

    def bot_on_revoke_floor(self, event: RevokeFloorEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_revoke_floor")
        self._has_floor = False

    def bot_on_utterance(self, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_utterance")
        utterance = DialogEvent(
            speakerUri=self._manifest.identification.speakerUri,
            features={"text": TextFeature(values=["Sorry! I'm a simple bot that has not been programmed to do anything yet."])}
        )
        out_envelope.events.append(UtteranceEvent(dialogEvent=utterance))

    def bot_on_context(self, event: ContextEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_context")
        self._current_context.append(event)

    def bot_on_uninvite(self, event: UninviteEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_uninvite")
        self._active_conversation = None

    def bot_on_get_manifests(self, event: GetManifestsEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
        print("Entering bot_on_get_manifests")
        out_envelope.events.append(
            PublishManifestsEvent(
                parameters=Parameters({
                    "servicingManifests": [self._manifest],
                    "discoveryManifests": []
                })
            )
        )
