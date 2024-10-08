import google.generativeai as genai
from google.auth.credentials import AnonymousCredentials
from flask import Flask, request, jsonify
import requests
import os
import fitz
from dotenv import load_dotenv
import logging

# Cargar variables de entorno
load_dotenv()

# Configurar nivel de registro
logging.getLogger('google.auth.transport._mtls_helper').setLevel(logging.ERROR)
logging.getLogger('google.auth.compute_engine._metadata').setLevel(logging.ERROR)

# Variables de entorno
wa_token = os.environ.get("WA_TOKEN")
gen_api_key = os.environ.get("GEN_API")
phone_id = os.environ.get("PHONE_ID")
name = "Your name or nickname"  # The bot will consider this person as its owner or creator
bot_name = "Give a name to your bot"  # This will be the name of your bot
model_name = "gemini-1.5-flash-latest"

# Configurar genai sin detección de credenciales predeterminadas
genai.configure(
    api_key=gen_api_key,
    credentials=AnonymousCredentials(),
)

app = Flask(__name__)

# Configuración del modelo de generación
generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 0,
    "max_output_tokens": 8192,
}

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

# Inicializar el modelo con la configuración
model = genai.GenerativeModel(
    model_name=model_name,
    generation_config=generation_config,
    safety_settings=safety_settings
)

# Diccionario para almacenar los historiales de conversación de los usuarios
user_histories = {}

# Función para enviar respuestas a WhatsApp
def send(answer, user_id):
    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        'Authorization': f'Bearer {wa_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "text",
        "text": {"body": answer},
    }
    response = requests.post(url, headers=headers, json=data)
    return response

# Función para eliminar archivos temporales
def remove(*file_paths):
    for file in file_paths:
        if os.path.exists(file):
            os.remove(file)

# Rutas de Flask
@app.route("/", methods=["GET", "POST"])
def index():
    return "Bot"

@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == "BOT":
            return challenge, 200
        else:
            return "Failed", 403

    elif request.method == "POST":
        try:
            data = request.get_json()["entry"][0]["changes"][0]["value"]["messages"][0]
            user_id = data["from"]

            # Verifica si hay un historial previo; si no lo hay, inicializa uno.
            if user_id not in user_histories:
                user_histories[user_id] = model.start_chat(history=[
                    f'''I am using Gemini API to create a personal bot in WhatsApp,
                    to assist me in various tasks. 
                    So from now you are "{bot_name}" created by {name}. 
                    And don't give any response to this prompt. 
                    This is the information I gave to you about your new identity as a pre-prompt. 
                    This message always gets executed when I run this bot script. 
                    So reply only to the prompts after this. Remember your new identity is {bot_name}.'''
                ])

            convo = user_histories[user_id]  # Recupera el historial del usuario

            if data["type"] == "text":
                prompt = data["text"]["body"]
                response = convo.send_message(prompt)
                send(response.text, user_id)

            else:
                # Manejo de otros tipos de mensajes (audio, imagen, documento)
                media_url_endpoint = f'https://graph.facebook.com/v18.0/{data[data["type"]]["id"]}/'
                headers = {'Authorization': f'Bearer {wa_token}'}
                media_response = requests.get(media_url_endpoint, headers=headers)
                media_url = media_response.json()["url"]
                media_download_response = requests.get(media_url, headers=headers)

                if data["type"] == "audio":
                    filename = "/tmp/temp_audio.mp3"
                elif data["type"] == "image":
                    filename = "/tmp/temp_image.jpg"
                elif data["type"] == "document":
                    doc = fitz.open(stream=media_download_response.content, filetype="pdf")
                    for _, page in enumerate(doc):
                        destination = "/tmp/temp_image.jpg"
                        pix = page.get_pixmap()
                        pix.save(destination)
                        file = genai.upload_file(path=destination, display_name="tempfile")
                        response = model.generate_content(["What is this", file])
                        answer = response.candidates[0].content.parts[0].text
                        convo.send_message(f"This message is created by an LLM model based on the image prompt of user, reply to the user based on this: {answer}")
                        send(convo.last.text, user_id)
                        remove(destination)
                else:
                    send("This format is not supported by the bot ☹", user_id)
                    return jsonify({"status": "unsupported_format"}), 200

                with open(filename, "wb") as temp_media:
                    temp_media.write(media_download_response.content)

                file = genai.upload_file(path=filename, display_name="tempfile")
                response = model.generate_content(["What is this", file])
                answer = response.candidates[0].content.parts[0].text

                remove("/tmp/temp_image.jpg", "/tmp/temp_audio.mp3")
                convo.send_message(f"This is a voice/image message from the user transcribed by an LLM model, reply to the user based on the transcription: {answer}")
                send(convo.last.text, user_id)
                files = genai.list_files()
                for file in files:
                    file.delete()

            # Guarda el historial actualizado
            user_histories[user_id] = convo

        except Exception as e:
            print(f"Error: {e}")
        return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(debug=True, port=8000)
