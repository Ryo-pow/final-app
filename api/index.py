# Responseクラスとjsonライブラリを新しくインポートします
from fastapi import FastAPI, File, UploadFile, Query, Response, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import asyncio
import httpx
import urllib.parse
import logging # Add this line

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from vercel_blob import put
from tavily import TavilyClient
import google.generativeai as genai
from dotenv import load_dotenv # Add this line

load_dotenv() # Add this line

# --- APIキーの設定 ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") # Corrected
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY") # Corrected

if GEMINI_API_KEY:
    print("hogehoge",GEMINI_API_KEY)
    logging.info("GEMINI_API_KEY loaded successfully.")
else:
    logging.warning("GEMINI_API_KEY not found or is empty.")

if TAVILY_API_KEY:
    logging.info("TAVILY_API_KEY loaded successfully.")
else:
    logging.warning("TAVILY_API_KEY not found or is empty.")

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

# --- AI旅行プラン最適化機能 (最終決定版) ---
@app.get("/create-itinerary/")
async def create_itinerary(
    destinations: str = Query(...),
    date: str = Query(...),
    durations: str = Query(...),
    start_lat: float = Query(...),
    start_lon: float = Query(...),
):
    try:
        # Parameters are now directly available as function arguments
        # No need for request.query_params or params.get()

        # Convert durations string to list of ints
        durations_list = [int(d.strip()) for d in durations.split(',')]

        # Convert destinations string to list of names
        destination_names = [dest.strip() for dest in destinations.split(',')]

        print(f"DEBUG: destinations received: '{destinations}'") # 追加
        print(f"DEBUG: destination_names: {destination_names}, len: {len(destination_names)}") # 追加
        print(f"DEBUG: durations received: '{durations}'") # 追加
        print(f"DEBUG: durations_list: {durations_list}, len: {len(durations_list)}") # 追加

        if not all([destinations, date, durations, start_lat, start_lon]): # Check for empty strings/None for required fields
            return JSONResponse(status_code=400, content={"message": "Missing required query parameters: destinations, date, durations, start_lat, start_lon"})

        if len(destination_names) != len(durations_list):
            return JSONResponse(status_code=400, content={"message": "The number of destinations and durations must be the same."})

        headers = {'User-Agent': 'FinalApp/1.0 (ryo-pow)'}
        locations = [{"name": "現在地", "lat": start_lat, "lon": start_lon}]
        dest_details = []

        

        headers = {'User-Agent': 'FinalApp/1.0 (ryo-pow)'}
        locations = [{"name": "現在地", "lat": start_lat, "lon": start_lon}]
        dest_details = []

        async with httpx.AsyncClient(timeout=30.0) as client: # timeout=30.0 を追加
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
                
                lat = float(geo_data[0]["lat"])
                lon = float(geo_data[0]["lon"])
                locations.append({"name": destination_names[i], "lat": lat, "lon": lon})
                dest_details.append({"name": destination_names[i], "duration_minutes": durations_list[i]})

            first_dest = locations[1]
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={first_dest['lat']}&longitude={first_dest['lon']}&daily=weathercode,temperature_2m_max,precipitation_probability_max&timezone=Asia%2FTokyo&start_date={date}&end_date={date}"
            
            coords_str = ";".join([f"{loc['lon']},{loc['lat']}" for loc in locations])
            osrm_driving_url = f"http://router.project-osrm.org/table/v1/driving/{coords_str}"
            osrm_walking_url = f"http://router.project-osrm.org/table/v1/walking/{coords_str}"

            weather_task = client.get(weather_url)
            osrm_driving_task = client.get(osrm_driving_url)
            osrm_walking_task = client.get(osrm_walking_url)

            weather_response, osrm_driving_response, osrm_walking_response = await asyncio.gather(weather_task, osrm_driving_task, osrm_walking_task)
            weather_response.raise_for_status()
            osrm_driving_response.raise_for_status()
            osrm_walking_response.raise_for_status()

            weather_data = weather_response.json().get('daily', {})
            weather_info = f"天気予報: 最高気温 {weather_data.get('temperature_2m_max', ['N/A'])[0]}℃, 降水確率 {weather_data.get('precipitation_probability_max', ['N/A'])[0]}%"
            durations_driving_matrix = osrm_driving_response.json()['durations']
            durations_walking_matrix = osrm_walking_response.json()['durations']

        prompt = f"""
        あなたは旅行プランナーAIです。以下の情報をもとに、訪問順に最適な旅行プランを立ててください。

【旅行情報】
- 旅行開始日時: 2025年9月10日 09:00
- 出発地: 東京駅
- 行きたい場所: 上野動物園、浅草寺、スカイツリー

【制約事項】
- 出発地点（東京駅）から始めて開始時間を基準とし、すべての目的地を順番に巡ってください。
- 各訪問地には「滞在時間」を適切に設定してください（例: 30〜90分)。
- 交通手段は「徒歩」または「車」のみを使用してください。
- 各訪問ステップは、必ず以下の5つの項目をこの順番で含めてください：

  1. "time"（到着または出発時刻。形式: ISO 8601、例 "2025-09-10T09:00"）
  2. "place"（訪問地名）
  3. "duration"（滞在時間、例: "60分"）
  4. "transportation"（「徒歩」または「車」のいずれか）
  5. "travel_time"（前の地点からの移動時間、例: "15分"）

- 最初のステップ（出発地点）は滞在時間0分、移動時間0分、交通手段は「徒歩」で構いません。

--ここからはjsonフォーマットの例です。--
[
  {
    "time": "2025-09-10T09:00",
    "place": "東京駅",
    "duration": "0分",
    "transportation": "徒歩",
    "travel_time": "0分"
  },
  {
    "time": "2025-09-10T09:20",
    "place": "上野動物園",
    "duration": "60分",
    "transportation": "車",
    "travel_time": "20分"
  }

【注意】

出力は有効なJSON形式のみで返してください。説明文やコメントは不要です。

JSONの構文に誤りがないようにしてください（クォーテーションやカンマの位置など。

各訪問地の「順番」「移動手段」「移動時間」「滞在時間」が論理的になるように調整してください。
        """
        
        ai_response = await model.generate_content_async(prompt)
        return JSONResponse(content={"plan": ai_response.text})

    except Exception as e:
        # エラーメッセージをより詳細に出力
        print(f"ERROR: Exception type: {type(e).__name__}, Args: {e.args}") # 追加
        return JSONResponse(status_code=500, content={"message": f"An error occurred: {type(e).__name__} - {e}"}) # 修正

# --- AIパーキングアシスタント機能 (バグ修正版) ---
@app.get("/nearby-parking/")
async def get_nearby_parking(lat: float = Query(...), lon: float = Query(...)):
    try:
        overpass_query = f"[out:json];(node(around:1000,{lat},{lon})[amenity=parking];way(around:1000,{lat},{lon})[amenity=parking];relation(around:1000,{lat},{lon})[amenity=parking];);out center;"
        overpass_url = "https://overpass-api.de/api/interpreter"
        params = {"data": overpass_query}

        async with httpx.AsyncClient() as client:
            response = await client.get(overpass_url, params=params, timeout=30.0)
            response.raise_for_status()
            parking_data = response.json()

        parking_lots = []
        for element in parking_data.get('elements', []):
            tags = element.get('tags', {})
            center = element.get('center', {})
            parking_lots.append({
                "name": tags.get('name', '名称不明'),
                "lat": element.get('lat') or center.get('lat'),
                "lon": element.get('lon') or center.get('lon')
            })

        if not parking_lots:
            return JSONResponse(content={"message": "周辺に駐車場が見つかりませんでした。", "parking_lots": []})

        # AIに分析を依頼
        prompt = f"""
        # 役割
        あなたは、日本の駐車事情に詳しい、親切なアシスタントです。

        # 状況
        ユーザーは、緯度:{lat}, 経度:{lon} の地点へ車で向かおうとしています。
        周辺の駐車場リストは以下の通りです。
        {parking_lots}

        # 指示
        これらの情報と、あなたが知っているその地域の一般的な駐車場の混雑具合や料金の傾向、道の広さなどを考慮して、ユーザーに役立つ駐車戦略をアドバイスしてください。
        - どの駐車場が特におすすめか、その理由は何か。
        - 週末や特定の時間帯に避けるべき駐車場はあるか。
        - 何か注意すべき点（最大料金の有無、道の狭さなど）はあるか。
        具体的で、現実に役立つ、親切なアドバイスを日本語でお願いします。
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
