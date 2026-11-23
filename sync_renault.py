import asyncio
import os
import json
from datetime import datetime, timezone
import aiohttp
from renault_api.renault_client import RenaultClient

EMAIL = os.environ["RENAULT_EMAIL"]
PASSWORD = os.environ["RENAULT_PASSWORD"]
VIN = os.environ["RENAULT_VIN"]
FIREBASE_URL = os.environ["FIREBASE_DB_URL"].rstrip("/")

async def main():
    async with aiohttp.ClientSession() as websession:
        # Türkiye (tr_TR) bölgesi için güncel Gigya/Kamereon anahtarlarını otomatik çeker
        client = RenaultClient(websession=websession, locale="tr_TR")
        await client.session.login(EMAIL, PASSWORD)

        account_id = (await client.get_person()).accounts[0].accountId
        account = await client.get_api_account(account_id)
        vehicle = await account.get_api_vehicle(VIN)

        cockpit = await vehicle.get_cockpit()
        
        odometer = cockpit.totalMileage or 0
        fuel_liters = cockpit.fuelQuantity or 0
        range_km = cockpit.fuelAutonomy or 0
        now_iso = datetime.now(timezone.utc).isoformat()

        # Önceki kaydı Firebase'den oku (seyahat farkını hesaplamak için)
        prev_data = {}
        async with websession.get(f"{FIREBASE_URL}/vehicle/current.json") as resp:
            if resp.status == 200:
                prev_data = await resp.json() or {}

        prev_km = prev_data.get("odometer", 0)
        prev_fuel = prev_data.get("fuelLiters", fuel_liters)

        # Kilometre artışı varsa yeni seyahat olarak kaydet (en az 0.5 km)
        if prev_km > 0 and odometer > prev_km and (odometer - prev_km) >= 0.5:
            dist = round(odometer - prev_km, 2)
            fuel_used = max(0, round(prev_fuel - fuel_liters, 2))
            trip_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trip_payload = {
                "id": trip_id,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "endTime": datetime.now(timezone.utc).strftime("%H:%M"),
                "distanceKm": dist,
                "fuelUsedLiters": fuel_used,
                "odometerEnd": odometer
            }
            await websession.put(
                f"{FIREBASE_URL}/vehicle/trips/{trip_id}.json",
                json=trip_payload
            )

        # Güncel veriyi Firebase'e yaz
        current_payload = {
            "odometer": odometer,
            "fuelLiters": fuel_liters,
            "rangeKm": range_km,
            "lastUpdate": now_iso
        }
        await websession.put(
            f"{FIREBASE_URL}/vehicle/current.json",
            json=current_payload
        )
        print(f"Senkronizasyon başarılı: {odometer} km | {fuel_liters} L | {range_km} km menzil")

if __name__ == "__main__":
    asyncio.run(main())
