import os
import json
import time
import asyncio
import logging
import asyncpg
import websockets
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from openai import AsyncOpenAI
from pgvector.asyncpg import register_vector
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
EMBEDDING_MODEL = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.7

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
db_pool: asyncpg.Pool | None = None


async def init_connection(conn):
    await register_vector(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(
        SUPABASE_DB_URL,
        min_size=1,
        max_size=5,
        init=init_connection,
        statement_cache_size=0,  # transaction pooler 不支援 prepared statements
    )
    logger.info("[db] connection pool ready")
    yield
    await db_pool.close()


app = FastAPI(lifespan=lifespan)


async def search_faq(query: str) -> str:
    t0 = time.perf_counter()
    response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    query_vec = response.data[0].embedding
    t1 = time.perf_counter()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select answer, 1 - (embedding <=> $1::vector) as similarity
            from faq
            order by embedding <=> $1::vector
            limit 1
            """,
            query_vec,
        )
    t2 = time.perf_counter()

    similarity = float(row["similarity"])
    logger.info(
        f"[search] query={query} sim={similarity:.4f} "
        f"embed={(t1-t0)*1000:.0f}ms db={(t2-t1)*1000:.0f}ms"
    )

    if similarity < SIMILARITY_THRESHOLD:
        return "資料庫中找不到相關資訊。"
    return row["answer"]


@app.websocket("/ws")
async def websocket_endpoint(client_ws: WebSocket):
    await client_ws.accept()

    gemini_url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"

    async with websockets.connect(gemini_url) as gemini_ws:
        async def receive_from_client():
            try:
                while True:
                    data = await client_ws.receive_text()
                    await gemini_ws.send(data)
            except Exception as e:
                logger.error(f"[receive_from_client] error: {e}")

        async def receive_from_gemini():
            try:
                while True:
                    raw = await gemini_ws.recv()
                    if isinstance(raw, bytes):
                        response_text = raw.decode("utf-8")
                    else:
                        response_text = raw
                    response_data = json.loads(response_text)

                    if "toolCall" in response_data:
                        function_call = response_data["toolCall"]["functionCalls"][0]
                        call_id = function_call.get("id", "")
                        query = function_call["args"]["query"]
                        logger.info(f"[toolCall] query: {query}")

                        answer = await search_faq(query)

                        tool_response = {
                            "tool_response": {
                                "function_responses": [{
                                    "id": call_id,
                                    "name": "search_database",
                                    "response": {"output": answer}
                                }]
                            }
                        }
                        await gemini_ws.send(json.dumps(tool_response))

                    await client_ws.send_text(response_text)
            except Exception as e:
                logger.error(f"[receive_from_gemini] error: {e}")

        await asyncio.gather(receive_from_client(), receive_from_gemini())
