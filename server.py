import asyncio
import websockets
import json
import uuid
import math
import os
from datetime import datetime

# --- CONFIG ---
# 0.0.0.0 is required for Cloud hosting
HOST = '0.0.0.0'
# Render provides the PORT variable. Default to 8765 for local testing.
PORT = int(os.environ.get("PORT", 8765))

ADMIN_EMAIL = "admin@event.com"
ADMIN_PASSWORD = "admin"

# --- STATE ---
ZONES = {} 
USER_LOCATIONS = {}
CONNECTED_CLIENTS = {}

# --- LOGIC ---
def point_in_circle(ulat, ulon, zone):
    R = 6371000 # Earth radius in meters
    lat1, lat2 = math.radians(ulat), math.radians(zone['lat'])
    dlat = math.radians(zone['lat'] - ulat)
    dlon = math.radians(zone['lon'] - ulon)
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return (R * c) <= zone['radius']

def update_crowd_counts():
    for z in ZONES.values(): z['count'] = 0
    for u in USER_LOCATIONS.values():
        if u.get('role') == 'user' and 'lat' in u:
            for z in ZONES.values():
                if point_in_circle(u['lat'], u['lon'], z):
                    z['count'] += 1
    for z in ZONES.values():
        z['is_crowded'] = z['count'] > z['threshold']

async def broadcast_state():
    msg_admin = json.dumps({"type": "state_update", "payload": {"zones": ZONES, "users": USER_LOCATIONS}})
    msg_user = json.dumps({"type": "state_update", "payload": {"zones": ZONES, "users": {}}})
    
    tasks = []
    for ws, cid in CONNECTED_CLIENTS.items():
        try:
            role = USER_LOCATIONS.get(cid, {}).get('role', 'user')
            tasks.append(ws.send(msg_admin if role == 'admin' else msg_user))
        except:
            pass
    
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)

# --- WEBSOCKET HANDLER ---
async def ws_handler(ws):
    cid = str(uuid.uuid4())
    CONNECTED_CLIENTS[ws] = cid
    print(f"Client connected: {cid}")
    
    try:
        async for msg in ws:
            data = json.loads(msg)
            mtype = data.get("type")
            payload = data.get("payload")
            user_role = USER_LOCATIONS.get(cid, {}).get('role')

            if mtype == "login":
                email, password = payload.get('email'), payload.get('password')
                role = "admin" if email == ADMIN_EMAIL and password == ADMIN_PASSWORD else "user"
                USER_LOCATIONS[cid] = {"role": role, "connected_at": datetime.now().isoformat(), "email": email}
                await ws.send(json.dumps({"type": "login_success", "payload": {"role": role}}))
                await broadcast_state()

            elif mtype == "location_update":
                if cid in USER_LOCATIONS:
                    USER_LOCATIONS[cid].update(payload)
                    update_crowd_counts()
                    await broadcast_state()
            
            elif mtype == "ping":
                await ws.send(json.dumps({"type": "pong"}))

            elif user_role == "admin":
                if mtype == "create_zone":
                    zid = str(uuid.uuid4())
                    ZONES[zid] = {**payload, "count": 0, "is_crowded": False, "id": zid}
                elif mtype == "update_zone":
                    if payload.get('id') in ZONES:
                        ZONES[payload['id']].update(payload)
                elif mtype == "delete_zone":
                    if payload.get('id') in ZONES:
                        del ZONES[payload['id']]
                
                update_crowd_counts()
                await broadcast_state()

    except Exception as e:
        print(f"WS Error: {e}")
    finally:
        if ws in CONNECTED_CLIENTS: del CONNECTED_CLIENTS[ws]
        if cid in USER_LOCATIONS: del USER_LOCATIONS[cid]
        update_crowd_counts()
        await broadcast_state()

async def main():
    print(f"🚀 Server started on port {PORT}")
    async with websockets.serve(ws_handler, HOST, PORT):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopping...")