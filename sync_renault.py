import asyncio
import os
from datetime import datetime, timezone
import aiohttp
from renault_api.renault_client import RenaultClient

EMAIL = os.environ["RENAULT_EMAIL"]
PASSWORD = os.environ["RENAULT_PASSWORD"]
VIN = os.environ["RENAULT_VIN"].strip().upper()
FIREBASE_URL = os.environ["FIREBASE_DB_URL"].rstrip("/")

async def main():
    async with aiohttp.ClientSession() as websession:
        client = RenaultClient(websession=websession, locale="fr_FR", country="TR")
        await client.session.login(EMAIL, PASSWORD)

        person = await client.get_person()
        target_account = None
        target_vin = VIN

        # Tüm alt hesapları tara ve aracın olduğu doğru hesabı bul
        for acc in person.accounts:
            print(f"Hesap kontrol ediliyor: {acc.accountId} (Tip: {acc.accountType}, Durum: {acc.accountStatus})")
            api_acc = await client.get_api_account(acc.accountId)
            try:
                vehicles_resp = await api_acc.get_vehicles()
                if vehicles_resp.vehicleLinks:
                    for v in vehicles_resp.vehicleLinks:
                        print(f" -> Bulunan araç VIN: {v.vin}")
                        if v.vin == VIN or not target_account:
                            target_account = api_acc
                            target_vin = v.vin
            except Exception as e:
                print(f" -> Bu hesapta araç listelenemedi: {e}")

        if not target_account:
            raise Exception("Hiçbir My Renault alt hesabında kayıtlı araç bulunamadı!")

        print(f"Seçilen hesap ve araç: {target_vin}")
        vehicle = await target_account.get_api_vehicle(target_vin)
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
        print(f"BASARILI! {odometer} km | {fuel_liters} L | {range_km} km menzil Firebase'e yazildi.")

if __name__ == "__main__":
    asyncio.run(main())
