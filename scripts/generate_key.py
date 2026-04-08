"""Admin script to generate Axion license keys.

Usage:
    python scripts/generate_key.py customer@email.com pro 365

Arguments:
    email   - Customer email
    tier    - starter, pro, or enterprise (default: pro)
    days    - Days until expiry (default: 365)

KEEP THIS SCRIPT SECRET — do NOT distribute with the product.
"""

import sys
from pathlib import Path

# Add parent to path so we can import axion
sys.path.insert(0, str(Path(__file__).parent.parent))

from axion.runtime.license import generate_license_key, validate_license_key


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_key.py <email> [tier] [days]")
        print("  tier: starter, pro, enterprise (default: pro)")
        print("  days: expiry in days (default: 365)")
        sys.exit(1)

    email = sys.argv[1]
    tier = sys.argv[2] if len(sys.argv) > 2 else "pro"
    days = int(sys.argv[3]) if len(sys.argv) > 3 else 365

    print(f"Generating key for: {email}")
    print(f"  Tier: {tier}")
    print(f"  Expires in: {days} days")
    print()

    key = generate_license_key(email, tier, days)
    print(f"License Key:")
    print(f"  {key}")
    print()

    # Validate it
    info = validate_license_key(key)
    print(f"Validation: {'VALID' if info.valid else 'INVALID'}")
    print(f"  Tier: {info.tier}")
    print(f"  Email: {info.email}")
    print()
    print("Customer activation command:")
    print(f"  axion activate {key}")


if __name__ == "__main__":
    main()
