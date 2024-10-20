import json
import boto3
import os
import requests
import base64
from io import BytesIO

# Initialize Bedrock clients for both runtime and agent runtime
bedrock_runtime = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-west-2'
)

bedrock_agent_runtime_client = boto3.client(
    service_name='bedrock-agent-runtime',
    region_name='us-west-2'
)


# Global variables for the knowledge base

# Model and knowledge base configurations
modelArn = 'arn:aws:bedrock:us-west-2::foundation-model/meta.llama3-1-405b-instruct-v1:0'
knowledgeBaseId = '7EHLOYLSJL'


# Helper function to validate and fetch a required key from data
def get_required_key(data, key):
    if key not in data:
        raise KeyError(f"Missing required key: {key}")
    return data[key]

# Function to check the input type
def check_input_type(data):
    print("Trying to check input type of the payload")
    if(data.get('input_type') == None):
        print ("Input type not found")
        return False
    try:
        if 'audio' in data.get('input_type'):
            return "audio"
        elif 'text' in data.get('input_type'):
            return "text"
        else:
            return 'text'
    except json.JSONDecodeError:
        print("Invalid input type")
        return False

# Download the audio file from url using authentication token
def download_audio_file(url, token):
    print("Trying to download audio file")
    # Request headers for the audio file download
    headers = {
        'Authorization': f'App {token}'
    }
    # Request the audio file from the provided URL
    response = requests.get(url, headers=headers)
    # Encode the audio file in base64 format
    base64_audio = response.content.encode('base64')
    return audio_file

# Functino to translate speech to text using Sarvam AI
def translate_speech_to_text(data,api_key):
    print("Trying to translate speech to text")
    import requests

    url = "https://api.sarvam.ai/speech-to-text-translate"

    file_name = "voice.wav"
    file_bytes = base64.b64decode(data.get("question"))
    file_input = BytesIO(file_bytes)
    payload = {'model': 'saaras:v1'}
    files=[('file',(file_name,file_input,'audio/wav'))]
    
    headers = {
        'API-Subscription-Key': api_key
    }

    response = requests.request("POST", url, headers=headers, data=payload, files=files)
    
    print("Response from Sarvam AI: " + str(response.text))
    return [response.text[0],response.text[1]]

    

# Function to detect the language of the text using llama
def detect_text_lang(prompt):
    
    # Format prompt for language detection
    formatted_prompt = f"""
    You have received a text and you need to detect the language of the text.You also need to translate the text to English. Dont translate if the text is already in English.
    The text below is:
    {prompt}
    Use emoji wherever necessary
    Give the answer is the following format:
    Language Detected: <language_detected>
    Translated text: <translated text>
    Don't include any extra comments or text other than the answer format above.
    """
    
    # Request payload for the LLaMA model
    llama_request = json.dumps({
        "prompt": formatted_prompt,
        "max_gen_len": 250,
        "temperature": 0.5,
    })

    # Invoke the LLaMA model using the prepared payload
    response_llama = bedrock_runtime.invoke_model(
        modelId='meta.llama3-1-405b-instruct-v1:0',
        body=llama_request
    )
    
    # Decode the response body from the LLaMA model
    response_body = json.loads(response_llama["body"].read())
    print("Response from llama language translation: " + str(response_body))
    # Extract the language from the response
    language = response_body["generation"].split(":")[1].strip()
    translated_text = response_body["generation"].split(":")[2].strip()
    return [language,translated_text]

# Function to get rag response
def get_rag_response(prompt):
    # Format prompt for retrieval-augmented generation (RAG) with knowledge base
    rag_prompt = f"""
    Human: Please answer the question based on available knowledge.
    Question: {prompt}
    Assistant:
    """
    
    # Call the agent runtime to retrieve knowledge from the knowledge base and generate a response
    response_rag = bedrock_agent_runtime_client.retrieve_and_generate(
        input={
            'text': rag_prompt,
        },
        retrieveAndGenerateConfiguration={
            'type': 'KNOWLEDGE_BASE',   
            'knowledgeBaseConfiguration': {
                'knowledgeBaseId': knowledgeBaseId,
                'modelArn': modelArn,
            }
        }
    )
    
    # Parse the response from the RAG system (Knowledge Base response)
    response_output = response_rag['output']['text']
    return response_output

#Function to save audio response in base64 format to S3
def saveToS3(response,api_key):
    print("Trying to save audio response to S3")
    s3 = boto3.client('s3')
    # Create a byte stream from the base64 audio response
    audio_response = BytesIO(base64.b64decode(response))
    # Save the audio response to S3 creating a signed public URL
    s3.put_object(Bucket='llama-hack-folder', Key='output.wav', Body=audio_response)

    # Define bucket name and file name
    bucket_name = "llama-hack-folder"
    file_name = "output.wav"
    file_url = s3.generate_presigned_url('get_object', Params={'Bucket': bucket_name, 'Key': file_name})

    return file_url

#Generate audio response
def generate_audio_response(response,language_code,api_key):
    print("Trying to generate audio response")
    url = 'https://api.sarvam.ai/text-to-speech'
    headers = {"api-subscription-key":api_key,"Content-Type": "application/json"}
    if(response.length<5){
        response = "I'm sorry but I could not understand what you mean"
    }
    print("Response from Llama: " + str(response))
    print("Language code: " + str(language_code))
    
    if(language_code != "en-IN" or language_code != "hi-IN" or language_code != "mr-IN" or language_code != "kn-IN" or language_code != "te-IN"):
        language_code = "en-IN"
    payload = {
    "inputs": [response],
    "target_language_code": language_code,
    "speaker": "meera",
    "pitch": 0,
    "pace": 1.2,
    "loudness": 1.5,
    "speech_sample_rate": 8000,
    "enable_preprocessing": True,
    "model": "bulbul:v1"
    }
    response = requests.post(url, headers=headers, json=payload)
    print("Response from Sarvam AI TTS: " + str(response.text))
    base64output = response.json()['audios']
    s3_audio_url = saveToS3(str(base64output[0]),api_key)
    return s3_audio_url

#Function to get llama response
def get_llama_response(rag_response,data):
    print("Trying to get llama response")
    # Extract prompt and optional parameters from the request
    model_id = data.get("model", 'meta.llama3-1-8b-instruct-v1:0')
    prompt = data.get("question")
    max_gen_len = data.get("max_gen_len", 512)
    temperature = data.get("temp", 0.5)

    # We structure the prompt for LLaMA such that it incorporates the RAG response and asks LLaMA to augment it.

    formatted_prompt = f"""
    The following information is retrieved from a trusted knowledge base:
    {rag_response}
    
    Based on above response provide an answer that is similar to the above response.
    Don't give any other answer except the one that is similar to the above response and if the original prompt below is in some other language try and translate it.
    Don't repeat the question in the answer.
    Don't begin answer by asking a question. Directly provide the answer.
    Don't include any extra comments or text other than the answer format above.
    Don't begin the answer with Answer: or any other prefix.
    Avoid providing code, functions, or structured technical formats or any escape squences like new line or extra quotes.
    Question: {prompt}
    """

    # Request payload for the LLaMA model
    llama_request = json.dumps({
        "prompt": formatted_prompt,
        "max_gen_len": max_gen_len,
        "temperature": temperature,
    })

    # Invoke the LLaMA model using the prepared payload
    response_llama = bedrock_runtime.invoke_model(
        modelId=model_id,
        body=llama_request
    )
   
    
    # Decode the response body from the LLaMA model
    response_body = json.loads(response_llama["body"].read())  
    print("Response from llama: " + str(response_body))
    return response_body["generation"]

def handle_audio_input(data):
    print("Handling audio input")
    sarvam_api_key = os.getenv('SARVAM_API_KEY')
    translated_text = translate_speech_to_text(data,sarvam_api_key)
    rag_response = get_rag_response(translated_text[0])
    llama_response = get_llama_response(rag_response,data)
    audio_response = generate_audio_response(llama_response,translated_text[1],sarvam_api_key)
    return [rag_response,audio_response]

def handle_text_input(data):
    print("Handling text input")
    prompt = data.get("question")
    text_lang = detect_text_lang(prompt)
    print("Text language detected: " + text_lang[0])
    print("Translated text: " + text_lang[1])
    rag_response = get_rag_response(text_lang[1])
    llama_response = get_llama_response(rag_response,data)
    return [rag_response,llama_response]    

def prase_response(response):
    return response

# Main Lambda handler function
def lambda_handler(event, context):
    
    # Fetch expected authentication key from environment variable
    expected_key = os.getenv('AUTH_KEY')
    
    # Extract the 'Authorization' header from the incoming request
    auth_key = event.get('headers', {}).get('authorization')
    
    # Check for unauthorized access
    if auth_key != expected_key:
        return {
            'statusCode': 401,
            'body': json.dumps({"message": "Unauthorized"})
        }
    
    # Parse request body
    data = json.loads(event.get("body", "{}"))

    # Check if the 'question' is present in the request body
    if 'question' not in data:
        return {
            'statusCode': 400,
            'body': json.dumps({"message": "Prompt not found."})
        }

    # check input type
    input_type = check_input_type(data)
    prompt = data.get("question")

    response = None
    if input_type == "audio":
        response = handle_audio_input(data)
    elif input_type == "text":
        response = handle_text_input(data)
    else:
        return {
            'statusCode': 400,
            'body': json.dumps({"message": "Invalid input type"})
        }
    
    print("Response from the handler: " + str(response))
    parsedResponse = prase_response(response[1])
    
    # Return the combined response: knowledge-based output and LLaMA generation
    return {
        'statusCode': 200,
        'body': json.dumps(
            {
                "question": prompt,
                "input_type": input_type,
                "knowledge_base_response": response[0],
                "augmented_llama_response": parsedResponse
            }
        )
    }