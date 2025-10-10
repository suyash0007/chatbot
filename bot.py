from flask import Flask, request, jsonify
import requests
import os
from datetime import datetime
import pytz

app = Flask(__name__)

# Configuration
CHATWOOT_URL = "https://app.chatwoot.com" 
API_TOKEN = "wzMpqWfSCmMDtXjvtVv5r2iD"
ACCOUNT_ID = "137894"

# Conversation state storage (use Redis/Database in production)..
conversation_states = {}

def send_message(conversation_id, content, message_type="outgoing", content_type="text", content_attributes=None):
    """Send message via Chatwoot API"""
    try:
        url = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}/conversations/{conversation_id}/messages"
        headers = {
            "api_access_token": f"{API_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "content": content,
            "message_type": message_type,
            "private": False
        }
        
        if content_type != "text":
            payload["content_type"] = content_type
        if content_attributes:
            payload["content_attributes"] = content_attributes
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Message sent successfully to conversation {conversation_id}")
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def update_custom_attributes(conversation_id, new_attributes):
    """
    Update conversation custom attributes by merging with existing attributes.
    """
    try:
        # Step 1: Fetch existing custom attributes
        url_get = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}/conversations/{conversation_id}"
        headers = {
            "api_access_token": f"{API_TOKEN}"
        }
        response_get = requests.get(url_get, headers=headers)
        response_get.raise_for_status()
        
        current_attributes = response_get.json().get('custom_attributes', {})
        
        # Step 2: Merge new attributes with existing ones
        updated_attributes = {**current_attributes, **new_attributes}
        
        # Step 3: Send the merged attributes back to Chatwoot
        url_post = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}/conversations/{conversation_id}/custom_attributes"
        payload = {"custom_attributes": updated_attributes}
        
        response_post = requests.post(url_post, headers=headers, json=payload)
        response_post.raise_for_status()
        
        print(f"Custom attributes updated for conversation {conversation_id}: {updated_attributes}")
        return response_post.json()
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error updating custom attributes: {err}")
        return None
    except Exception as e:
        print(f"General Error updating custom attributes: {e}")
        return None

def update_conversation_status(conversation_id, status):
    """Update conversation status (pending/open/resolved)"""
    try:
        url = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}/conversations/{conversation_id}/toggle_status"
        headers = {
            "api_access_token": f"{API_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {"status": status}
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        print(f"Conversation {conversation_id} status updated to: {status}")
        return response.json()
    except Exception as e:
        print(f"Error updating conversation status: {e}")
        return None

def is_business_hours():
    """Check if current time is within business hours"""
    tz = pytz.timezone('Asia/Kolkata')
    current_time = datetime.now(tz)
    
    # Weekend check
    # if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
    #     return False
    
    # # Time check (9 AM - 6 PM)
    # if current_time.hour < 9 or current_time.hour >=24:
    #     return False
    
    return True

def send_options_message(conversation_id):
    """Send interactive options based on business hours"""
    if is_business_hours():
        options = [
            {"title": "Talk to our Executive", "value": "connect_agent"},
            {"title": "Book a Demo", "value": "book_demo"}
        ]
        content = "How would you like to proceed?"
    else:
        options = [
            {"title": "Book a Demo", "value": "book_demo"}
        ]
        content = "Our team is currently offline. You can book a demo at your convenience:"
    
    send_message(
        conversation_id,
        content,
        content_type="input_select",
        content_attributes={"items": options}
    )

def create_conversation(contact_id, inbox_id, source_id):
    """Create a new conversation via Chatwoot API"""
    try:
        url = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}/conversations"
        headers = {
            "api_access_token": API_TOKEN,
            "Content-Type": "application/json"
        }
        payload = {
            "source_id": source_id,
            "inbox_id": inbox_id,
            "contact_id": contact_id
        }
        
        print(f"Attempting to create conversation with payload: {payload}")
        
        response = requests.post(url, headers=headers, json=payload)
        
        print(f"API Response Status Code: {response.status_code}")
        print(f"API Response Body: {response.text}")
        
        response.raise_for_status()
        conversation_id = response.json().get('id')
        
        print(f"New conversation created with ID: {conversation_id}")
        return conversation_id
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error creating conversation: {err}")
        return None
    except Exception as e:
        print(f"General Error creating conversation: {e}")
        return None


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Main webhook handler"""
    data = request.json
    event = data.get('event')
    print(f"Received webhook event: {event}")
    print(f"Full payload: {data}")
    
    # Handle widget trigger event to create conversation and send first message
    if event == "webwidget_triggered":
        contact_id = data.get("contact", {}).get("id")
        inbox_id = data.get("inbox", {}).get("id")
        source_id = data.get("source_id")

        if contact_id and inbox_id and source_id:
            conversation_id = create_conversation(contact_id, inbox_id, source_id)
            if conversation_id:
                print(f"Widget triggered for conversation: {conversation_id}")
                # Initialize state and send first question
                conversation_states[conversation_id] = "awaiting_name"
                send_message(conversation_id, "Hi! Welcome to our support. What is your name?")
                return jsonify({"status": "success", "message": "First question sent"}), 200
        else:
            print("Missing required IDs in webwidget_triggered payload.")
            return jsonify({"status": "ignored", "reason": "Missing IDs"}), 200
    
    # Only process incoming messages for subsequent interactions
    if event != "message_created":
        return jsonify({"status": "ignored", "reason": "Not a message_created event"}), 200
    
    message_type = data.get("message_type")
    if message_type != "incoming":
        return jsonify({"status": "ignored", "reason": "Not an incoming message"}), 200
    
    conversation_id = data.get("conversation", {}).get("id")
    user_message = data.get("content", "").strip()
    
    print(f"Processing message from conversation {conversation_id}: {user_message}")
    
    # Get conversation state
    state = conversation_states.get(conversation_id, "unknown")
    print(f"Current state: {state}")
    
    # State machine for sequential questions
    if state == "awaiting_name":
        # Store name and ask next question
        update_custom_attributes(conversation_id, {"customer_name": user_message})
        send_message(conversation_id, "Great! What project do you want to deploy?")
        conversation_states[conversation_id] = "awaiting_project"
    
    elif state == "awaiting_project":
        # Store project and ask framework
        update_custom_attributes(conversation_id, {"project_name": user_message})
        send_message(conversation_id, "Interesting! What framework is it?")
        conversation_states[conversation_id] = "awaiting_framework"
    
    elif state == "awaiting_framework":
        # Store framework and show options
        update_custom_attributes(conversation_id, {"framework": user_message})
        send_options_message(conversation_id)
        conversation_states[conversation_id] = "awaiting_choice"
    
    elif state == "awaiting_choice":
        # Handle user's choice - check exact values from button clicks
        if user_message == "connect_agent":
            send_message(conversation_id, "Connecting you to our executive team. Someone will be with you shortly!")
            update_conversation_status(conversation_id, "open")
            conversation_states[conversation_id] = "handed_off"
        
        elif user_message == "book_demo":
            send_message(conversation_id, "Book your demo here: https://cal.com/your-booking-link")
            update_conversation_status(conversation_id, "resolved")
            conversation_states[conversation_id] = "completed"
        
        else:
            # Handle case where user types instead of clicking button
            send_message(conversation_id, "Please select one of the options above.")
    
    elif state == "handed_off":
        # Conversation is with human agent now, don't respond
        print(f"Conversation {conversation_id} is handed off to agent, ignoring message")
        return jsonify({"status": "ignored", "reason": "Handed off to agent"}), 200
    
    elif state == "completed":
        # Conversation is completed
        print(f"Conversation {conversation_id} is completed")
        return jsonify({"status": "ignored", "reason": "Conversation completed"}), 200
    
    else:
        # Unknown state - restart flow
        print(f"Unknown state for conversation {conversation_id}, restarting flow")
        conversation_states[conversation_id] = "awaiting_name"
        send_message(conversation_id, "Hi! What is your name?")
    
    return jsonify({"status": "success"}), 200

@app.route("/", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "message": "Chatwoot webhook server is active",
        "active_conversations": len(conversation_states)
    }), 200

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    print(f"Starting server on port {port}")
    print(f"Account ID: {ACCOUNT_ID}")
    print(f"Chatwoot URL: {CHATWOOT_URL}")
    app.run(host='0.0.0.0', port=port, debug=False)