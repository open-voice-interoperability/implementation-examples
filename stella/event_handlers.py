"""
OpenFloor event handlers for StellaAgent.

This module contains all the event handling logic separated from the main agent class
for better organization, maintainability, and testing.
"""

import openfloor
from openfloor.envelope import Envelope, Parameters
from openfloor.events import UtteranceEvent, PublishManifestsEvent
from openfloor.dialog_event import DialogEvent, TextFeature


def bot_on_invite(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle invite event.
    
    Check for "joining floor" in the invite or accompanying events,
    then accept the invitation and send a greeting utterance.
    Send "acceptInvite" or "declineInvite" accordingly.
    """
    # Check for "joining floor" in the invite or accompanying events
    agent.joinedFloor = False
    
    # Check if there are any utterance events in the envelope that mention "joining floor"
    for env_event in in_envelope.events:
        if hasattr(env_event, 'eventType') and env_event.eventType == 'utterance':
            # Extract text from utterance event
            try:
                dialog = None
                if hasattr(env_event, "parameters"):
                    dialog = env_event.parameters.get("dialogEvent")
                if dialog is None:
                    dialog = getattr(env_event, "dialogEvent", None)
                
                if dialog and hasattr(dialog, "features"):
                    text_feature = dialog.features.get("text")
                    if text_feature:
                        # Check values
                        if hasattr(text_feature, "values") and text_feature.values:
                            for value in text_feature.values:
                                if "joining floor" in str(value).lower():
                                    agent.joinedFloor = True
                                    break
                        # Check tokens
                        if hasattr(text_feature, "tokens") and text_feature.tokens:
                            for token in text_feature.tokens:
                                if hasattr(token, "value") and "joining floor" in str(token.value).lower():
                                    agent.grantedFloor = True
                                    break
                                elif isinstance(token, dict) and "joining floor" in str(token.get("value", "")).lower():
                                    agent.grantedFloor = True
                                    break
            except Exception:
                # If we can't parse the utterance, continue without error
                pass
                
            if agent.joinedFloor:
                break
    
    # Check invite event parameters for dialog history that might contain "joining floor"
    if not agent.joinedFloor and hasattr(event, "parameters"):
        try:
            dialog_history = event.parameters.get("dialogHistory", [])
            for dialog_event in dialog_history:
                if isinstance(dialog_event, dict) and "features" in dialog_event:
                    text_features = dialog_event.get("features", {}).get("text", {})
                    # Check tokens in dialog history
                    tokens = text_features.get("tokens", [])
                    for token in tokens:
                        token_value = token.get("value", "") if isinstance(token, dict) else str(token)
                        if "joining floor" in token_value.lower():
                            agent.joinedFloor = True
                            break
                if agent.joinedFloor:
                    break
        except Exception:
            pass
    
    # Accept the invitation (using parent class behavior)
    # Note: The actual acceptance would be handled by BotAgent.bot_on_invite
    name = agent._manifest.identification.conversationalName or agent._manifest.identification.speakerUri
    
    # Modify greeting based on whether we joined a floor
    if agent.joinedFloor:
        greeting = f"Hi, I'm {name}. I've joined the floor and I'm ready to help with space facts!"
    else:
        greeting = f"Hi, I'm {name}. How can I help with space facts today?"

    dialog = DialogEvent(
        speakerUri=agent._manifest.identification.speakerUri,
        features={"text": TextFeature(values=[greeting])}
    )
    out_envelope.events.append(UtteranceEvent(dialogEvent=dialog))


def bot_on_utterance(agent, event: UtteranceEvent, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle utterance event - process user input and generate response."""
    # If floor has been revoked, do not respond to utterances
    if getattr(agent, 'floorRevoked', False):
        print("Floor has been revoked - ignoring utterance")
        return
    
    # Extract the user text robustly
    try:
        # event.parameters may be a Parameters dict or contain dialogEvent directly
        dialog = None
        hasParameters = hasattr(event, "parameters")  
        isparametersDict = isinstance(event.parameters, dict)
        if hasattr(event, "parameters"):
            dialog = event.parameters.get("dialogEvent")
        if dialog is None:
            dialog = getattr(event, "dialogEvent", None)
    except Exception:
        dialog = getattr(event, "dialogEvent", None)

    user_text = None
    if dialog is not None:
        try:
            # dialog may be a DialogEvent instance or a dict-like
            if hasattr(dialog, "features") and dialog.features is not None:
                feat = dialog.features.get("text") if isinstance(dialog.features, dict) else getattr(dialog.features, "text", None)
                if feat is not None:
                    # Feature may be a TextFeature instance or a plain dict
                    if isinstance(feat, dict):
                        # dict may contain 'values' or 'tokens'
                        vals = feat.get("values")
                        if vals and isinstance(vals, list) and len(vals) > 0:
                            user_text = vals[0]
                        else:
                            tokens = feat.get("tokens") or []
                            if tokens and isinstance(tokens, list) and len(tokens) > 0:
                                # token may be dict or Token instance
                                t0 = tokens[0]
                                if isinstance(t0, dict):
                                    user_text = t0.get("value")
                                else:
                                    user_text = getattr(t0, "value", None)
                    else:
                        # TextFeature or Feature instance: check values then tokens
                        vals = getattr(feat, "values", None)
                        if vals:
                            # vals might be a list
                            try:
                                user_text = vals[0]
                            except Exception:
                                user_text = None
                        else:
                            tokens = getattr(feat, "tokens", None)
                            if tokens and len(tokens) > 0:
                                user_text = getattr(tokens[0], "value", None)
            elif isinstance(dialog, dict):
                # dialog dict path
                user_text = dialog["features"]["text"]["tokens"][0]["value"]
        except Exception as e:
            # Log the error but continue with empty user_text
            print(f"Error extracting user text from dialog: {e}")
            user_text = None

    if user_text is None:
        user_text = ""

    # Maintain conversation state keyed by conversation id
    conv_id = in_envelope.conversation.id if in_envelope and in_envelope.conversation else None
    if conv_id is not None and conv_id not in agent._conversation_state:
        agent._conversation_state[conv_id] = {}

    reply_text = agent.generate_openai_response(user_text, conv_id)

    # Append the assistant's utterance to the outgoing envelope
    dialog_out = DialogEvent(
        speakerUri=agent._manifest.identification.speakerUri,
        features={"text": TextFeature(values=["here is the information you requested about " + user_text])}
    )
    
    # Import is_html_string from the main module
    from stella_agent import is_html_string
    from openfloor.dialog_event import Token
    
    if reply_text and is_html_string(reply_text):
        htmlFeature = openfloor.dialog_event.Feature(mimeType="text/html", tokens=[Token(value=reply_text)])
        # change the mimeType to text/html if the reply looks like HTML
        dialog_out.features["html"] = htmlFeature
    out_envelope.events.append(UtteranceEvent(dialogEvent=dialog_out))


def bot_on_get_manifests(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle get manifests event - return agent capabilities."""
    # Respond with the manifest we were constructed with
    out_envelope.events.append(
        PublishManifestsEvent(parameters=Parameters({"servicingManifests": [agent._manifest], "discoveryManifests": []}))
    )
    print("envelope after appending manifest event" + str(out_envelope))


def bot_on_grant_floor(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle grant_floor event.
    
    This event is triggered when an agent is granted the floor to speak.
    Two cases: this agent is granted the floor or another agent is granted the floor.
    If this agent is granted the floor, and it has something to say, it should send an utterance event.
    If this agent is granted the floor, and it has nothing to say, it should send an empty event.
    If another agent is granted the floor, this agent should send an empty event.
    """
    agent.grantedFloor = True
    agent.floorRevoked = False  # Reset revoked flag when floor is granted


def bot_on_decline_invite(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle decline_invite event.
    
    This event is triggered when an invitation to join a conversation is declined.
    This event would come from another agent on the floor and does not require any response 
    from the agent -- it would be handled by the floor or convener.
    """
    # Just send an empty response
    pass


def bot_on_uninvite(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle uninvite event.
    
    This event is triggered when an agent is uninvited/removed from a conversation.
    """
    # TODO: Implement uninvite event handling logic
    # For now, this is just a stub that can be expanded based on requirements
    pass


def bot_on_revoke_floor(agent, event, in_envelope: Envelope, out_envelope: Envelope) -> None:
    """Handle revoke_floor event.
    
    This event is triggered when the agent's floor permissions are revoked.
    """
    agent.grantedFloor = False
    agent.floorRevoked = True
    print("Floor has been revoked - will not respond to further utterances")