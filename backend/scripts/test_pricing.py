"""Smoke-test the pricing service directly."""
import asyncio, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.pricing import PricingService


async def main():
    ps = PricingService()
    try:
        for country in ("US", "GB"):
            print(f"\n--- {country}: 'The Great Gatsby' F. Scott Fitzgerald ---")
            rc = await ps.price_book_new("The Great Gatsby", "F. Scott Fitzgerald", "", country)
            uv = await ps.price_book_used("The Great Gatsby", "F. Scott Fitzgerald", "", country)
            print(f"  new : {rc.currency} {rc.amount}  src={rc.source}  err={rc.error}")
            print(f"        {rc.url}")
            print(f"  used: {uv.currency} {uv.amount}  src={uv.source}  err={uv.error}")
            print(f"        {uv.url}")
    finally:
        await ps.close()


if __name__ == "__main__":
    asyncio.run(main())
