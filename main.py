from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel
import httpx
import os
import json
import traceback
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import pytz
from dotenv import load_dotenv
from typing import Optional, List

load_dotenv()

# Create logs directory if it doesn't exist
os.makedirs('/app/logs', exist_ok=True)

# Configure rotating file handler
file_handler = RotatingFileHandler(
   '/app/logs/rei_service.log',
   maxBytes=10*1024*1024,  # 10MB per file
   backupCount=10  # Keep 5 backup files
)

# Configure logging
logging.basicConfig(
   level=logging.INFO,
   format='%(asctime)s UTC - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
   handlers=[
       file_handler,
       logging.StreamHandler()
   ]
)

# Set timezone to UTC
def utc_converter(*args):
   return datetime.now(pytz.UTC).timetuple()

logging.Formatter.converter = utc_converter
logger = logging.getLogger(__name__)

app = FastAPI()

logger.info("Starting REI Service...")

# Load REI agents dynamically from environment
rei_agents = {}
for key, value in os.environ.items():
   if key.startswith("REI_AGENT_SECRET_") and value:
       unit_name = key.replace("REI_AGENT_SECRET_", "").lower()
       rei_agents[unit_name] = value

if not rei_agents:
   logger.error("No REI agent secrets found!")
else:
   logger.info(f"Loaded {len(rei_agents)} REI agents: {list(rei_agents.keys())}")

class Query(BaseModel):
   text: str
   token_watchlist: Optional[List[dict]] = None

@app.post("/chat/{unit_id}")
async def chat_with_specific_unit(
   unit_id: str = Path(..., description="REI unit identifier"),
   query: Query = ...
):
   try:
       logger.info(f"=== INCOMING REQUEST ===")
       logger.info(f"Unit ID: {unit_id}")
       logger.info(f"Full incoming payload: {json.dumps(query.dict(), indent=2, ensure_ascii=False)}")
       
       if unit_id not in rei_agents:
           logger.error(f"Unit '{unit_id}' not found in rei_agents: {list(rei_agents.keys())}")
           raise HTTPException(
               status_code=404, 
               detail=f"REI unit '{unit_id}' not found. Available units: {list(rei_agents.keys())}"
           )

       # Use raw text without sanitization
       content_text = query.text
       logger.info(f"Using raw text (length: {len(content_text)} characters)")

       headers = {
           "Authorization": f"Bearer {rei_agents[unit_id][:10]}...{rei_agents[unit_id][-4:]}",  # Partial secret for security
           "Content-Type": "application/json"
       }
       payload = {
           "messages": [{"role": "user", "content": content_text}]
       }
       
       logger.info(f"=== OUTGOING REQUEST TO REI API ===")
       logger.info(f"Target URL: https://api.reisearch.box/rei/agents/chat-completion")
       logger.info(f"Headers (with masked auth): {headers}")
       logger.info(f"Full outgoing payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
       
       async with httpx.AsyncClient(timeout=3000.0) as client:
           response = await client.post(
               "https://api.reisearch.box/rei/agents/chat-completion",
               json=payload,
               headers={
                   "Authorization": f"Bearer {rei_agents[unit_id]}",  # Use full secret for actual request
                   "Content-Type": "application/json"
               }
           )

       logger.info(f"=== REI API RESPONSE ===")
       logger.info(f"Response status code: {response.status_code}")
       logger.info(f"Response headers: {dict(response.headers)}")
       
       if response.status_code == 401:
           logger.error(f"Unauthorized for unit '{unit_id}' - check secret key")
           raise HTTPException(status_code=401, detail="Unauthorized")
       elif response.status_code == 404:
           logger.error(f"Agent not found for unit '{unit_id}'")
           raise HTTPException(status_code=404, detail="Agent not found")
       elif response.status_code != 200:
           logger.error(f"REI API error response body: {response.text}")
           raise HTTPException(status_code=response.status_code, detail=f"API error: {response.text}")

       response_data = response.json()
       logger.info(f"Full REI API response body: {json.dumps(response_data, indent=2, ensure_ascii=False)}")
       
       content = ""
       if 'choices' in response_data and len(response_data['choices']) > 0:
           content = response_data['choices'][0].get('message', {}).get('content', '')
       
       final_response = {
           "content": content,
           "unit": unit_id,
           "raw_input_length": len(content_text),
           "raw_response": response_data
       }
       
       logger.info(f"=== FINAL RESPONSE TO CLIENT ===")
       logger.info(f"Response summary: content_length={len(content)}, unit={unit_id}")
       logger.info(f"Full response payload: {json.dumps(final_response, indent=2, ensure_ascii=False)}")
       
       return final_response

   except HTTPException:
       raise
   except httpx.ReadTimeout:
       logger.error(f"REI API timed out for unit '{unit_id}'")
       raise HTTPException(status_code=504, detail="The REI API took too long to respond (over 50 minutes). Try a simpler query or check back later.")
   except Exception as e:
       logger.error(f"ERROR in chat with unit '{unit_id}': {type(e).__name__}: {e}")
       logger.error(f"Full traceback: {traceback.format_exc()}")
       raise HTTPException(status_code=500, detail=str(e))

@app.get("/units")
async def list_available_units():
   """List all available REI units"""
   logger.info("Units endpoint accessed")
   response = {
       "units": list(rei_agents.keys()),
       "count": len(rei_agents)
   }
   logger.info(f"Units response: {json.dumps(response, indent=2)}")
   return response

@app.get("/health")
async def health_check():
   logger.info("Health check accessed")
   response = {"status": "healthy", "units_configured": len(rei_agents)}
   logger.info(f"Health response: {json.dumps(response, indent=2)}")
   return response
