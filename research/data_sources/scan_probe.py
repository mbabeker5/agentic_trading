import asyncio, time
from ib_async import IB, ScannerSubscription, TagValue
errors = {}
def on_err(reqId, code, msg, *a):
    if code in (2104,2106,2107,2108,2158): return
    errors.setdefault(reqId, []).append((code, msg[:90]))
async def main():
    ib = IB(); ib.errorEvent += on_err
    await ib.connectAsync('127.0.0.1', 4002, clientId=77, timeout=20)
    tests = [
      ("TOP_PERC_GAIN, no filters", "TOP_PERC_GAIN", []),
      ("TOP_PERC_GAIN, priceAbove 5 + stVolume5MinAbove 100000", "TOP_PERC_GAIN", [TagValue("priceAbove","5"), TagValue("stVolume5MinAbove","100000")]),
      ("HOT_BY_VOLUME, marketCapAbove 1e9", "HOT_BY_VOLUME", [TagValue("marketCapAbove","1000000000")]),
    ]
    for label, code, tags in tests:
        sub = ScannerSubscription(instrument='STK', locationCode='STK.US.MAJOR', scanCode=code, numberOfRows=50)
        t=time.time()
        try:
            rows = await asyncio.wait_for(ib.reqScannerDataAsync(sub, [], tags), timeout=30)
            n=len(rows); sample=[r.contractDetails.contract.symbol for r in rows[:5]]
        except Exception as e:
            n=-1; sample=[f"EXC {type(e).__name__}: {e}"[:80]]
        print(f"{label}: rows={n} in {time.time()-t:.1f}s sample={sample}")
    await asyncio.sleep(1)
    print("errors by reqId:", errors if errors else "none")
    ib.disconnect()
asyncio.run(main())
