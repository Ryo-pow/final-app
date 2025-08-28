# Responseクラスとjsonライブラリを新しくインポートします
from fastapi import FastAPI, File, UploadFile, Query, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import asyncio
import httpx

from vercel_blob import put
from tavily import TavilyClient
import google.generativeai as genai

# --- APIキーの設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}

# --- 天気予報機能 ---
@app.get("/weather/")
async def get_weather(latitude: float = Query(...), longitude: float = Query(...)):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Asia%2FTokyo"
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            weather_data = response.json()
            return JSONResponse(status_code=200, content=weather_data)
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI検索機能 ---
@app.get("/ai-search/")
async def ai_search(query: str = Query(...)):
    try:
        # This is a synchronous call, but for simplicity, we leave it as is.
        # If this becomes a bottleneck, Tavily's async client could be used.
        context = tavily.search(query=query, search_depth="advanced")
        prompt = f"""
        以下の検索結果を参考にして、ユーザーの質問に日本語で分かりやすく答えてください。
        ユーザーの質問: {query}
        検索結果: {context}
        """
        response = await model.generate_content_async(prompt)
        return JSONResponse(content={"answer": response.text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- AI旅行プラン最適化機能 (軽量化版) ---
@app.get("/create-itinerary/")
async def create_itinerary(request: Request):
    try:
        params = request.query_params
        destinations = params.get("destinations")
        start_lat_str = params.get("start_lat")
        start_lon_str = params.get("start_lon")

        if not all([destinations, start_lat_str, start_lon_str]):
            return JSONResponse(status_code=400, content={"message": "Missing required query parameters"})

        start_lat = float(start_lat_str)
        start_lon = float(start_lon_str)
        destination_names = [dest.strip() for dest in destinations.split(',')]
        
        headers = {'User-Agent': 'FinalApp/1.0 (ryo-pow)'}
        locations = [{"name": "現在地", "lat": start_lat, "lon": start_lon}]

        async with httpx.AsyncClient() as client:
            # --- ステップ1: 全地点の緯度・経度を並列で特定 ---
            geocoding_tasks = []
            for name in destination_names:
                search_query = f"{name}, 日本"
                url = f"https://nominatim.openstreetmap.org/search?q={search_query}&format=json&limit=1"
                geocoding_tasks.append(client.get(url, headers=headers))
            
            geocoding_responses = await asyncio.gather(*geocoding_tasks)

            for i, response in enumerate(geocoding_responses):
                response.raise_for_status()
                geo_data = response.json()
                if not geo_data:
                    return JSONResponse(status_code=404, content={"message": f"目的地が見つかりませんでした: {destination_names[i]}"})
                locations.append({
                    "name": destination_names[i],
                    "lat": float(geo_data[0]["lat"]),
                    "lon": float(geo_data[0]["lon"])
                })

            # --- ステップ2 & 3: 天気とルート情報を並列で取得 ---
            first_dest = locations[1]
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={first_dest['lat']}&longitude={first_dest['lon']}&daily=weathercode,temperature_2m_max,precipitation_probability_max&timezone=Asia%2FTokyo"
            
            coords_str = ";".join([f"{loc['lon']},{loc['lat']}" for loc in locations])
            osrm_url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}"

            weather_task = client.get(weather_url)
            osrm_task = client.get(osrm_url)

            weather_response, osrm_response = await asyncio.gather(weather_task, osrm_task)
            weather_response.raise_for_status()
            osrm_response.raise_for_status()

            weather_data = weather_response.json().get('daily', {})
            weather_info = f"天気予報: 最高気温 {weather_data.get('temperature_2m_max', ['N/A'])[0]}℃, 降水確率 {weather_data.get('precipitation_probability_max', ['N/A'])[0]}%"
            durations_matrix = osrm_response.json()['durations']

        # --- ステップ4: AIへの指示 ---
        prompt = f"""
        # ... (prompt content is the same as before) ...
        """
        
        ai_response = await model.generate_content_async(prompt)
        return JSONResponse(content={"plan": ai_response.text})

    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {str(e)}"})

# --- 画像アップロード機能 ---
@app.post("/upload-image/")
async def upload_image(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        blob_result = put(
            file.filename,
            contents,
            options={'add_random_suffix': True, 'access': 'public'}
        )
        return JSONResponse(
            status_code=200,
            content={"message": "Image uploaded successfully!", "url": blob_result['url']}
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"message": f"An error occurred: {str(e)}"}
        )