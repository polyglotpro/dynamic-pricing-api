import io
import pandas as pd
from fastapi import UploadFile, HTTPException
from pydantic import ValidationError

from app.models import SKUInput


REQUIRED_COLUMNS = {
    "sku_id",
    "product_name",
    "current_price",
    "cost",
    "current_ad_spend_per_unit",
    "conversion_rate",
    "roas",
    "stock_on_hand",
    "days_of_cover",
    "ageing_days",
    "sell_through_rate_weekly",
    "stockout_risk",
}


def _clean_record(record: dict) -> dict:
    cleaned = {}
    for key, value in record.items():
        if pd.isna(value):
            cleaned[key] = None
        elif key == "hero_sku":
            if isinstance(value, bool):
                cleaned[key] = value
            else:
                cleaned[key] = str(value).strip().lower() in ["true", "1", "yes", "y"]
        else:
            cleaned[key] = value
    return cleaned


async def read_sku_csv(file: UploadFile) -> list[SKUInput]:
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file")

    content = await file.read()

    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to read CSV: {exc}")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {sorted(missing)}"
        )

    records = []
    errors = []

    for index, row in df.iterrows():
        raw = _clean_record(row.to_dict())
        try:
            records.append(SKUInput(**raw))
        except ValidationError as exc:
            errors.append({
                "row_number": int(index) + 2,
                "sku_id": raw.get("sku_id"),
                "error": exc.errors()
            })

    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    return records
