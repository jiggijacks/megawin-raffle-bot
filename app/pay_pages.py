# app/pay_pages.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
import os, httpx

router = APIRouter()
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
CURRENCY = os.getenv("CURRENCY", "NGN")

@router.get("/pay/ps")
async def paystack_create_and_redirect(ref: str = Query(...), tg: str = Query(...), amt: int = Query(...)):
    """
    Initialize a Paystack transaction server-side and redirect the user to the checkout page.
    ref: merchant reference
    tg: telegram user id to include in metadata
    amt: amount in kobo (int)
    """
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Paystack not configured")

    body = {
        "email": f"user{tg}@example.com",
        "amount": amt,
        "currency": CURRENCY,
        "reference": ref,
        "metadata": {"tg_user_id": tg}
    }
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post("https://api.paystack.co/transaction/initialize", json=body, headers=headers)
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Paystack error: {resp.text}")
    data = resp.json().get("data") or {}
    auth_url = data.get("authorization_url")
    if not auth_url:
        raise HTTPException(status_code=502, detail="No authorization_url received")
    return RedirectResponse(auth_url)
