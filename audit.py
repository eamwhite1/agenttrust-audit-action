"""
AgentTrust GitHub Action — audit.py
Fetches the PR diff, pays the audit fee, calls the Referee, and sets
step outputs + exit code.
"""

import os
import sys
import json
import subprocess
import httpx
from xrpl.clients import JsonRpcClient
from xrpl.models.transactions import Payment
from xrpl.wallet import Wallet
from xrpl.utils import xrp_to_drops
from xrpl.transaction import submit_and_wait

REFEREE_URL   = os.environ["AT_REFEREE_URL"].rstrip("/")
JOB_SPEC      = os.environ["AT_JOB_SPEC"]
THRESHOLD     = int(os.environ.get("AT_THRESHOLD", "70"))
METHOD        = os.environ.get("AT_PAYMENT_METHOD", "xrp").lower()
XRP_SECRET    = os.environ.get("AT_XRP_SECRET", "")
USDC_KEY      = os.environ.get("AT_USDC_KEY", "")
MAX_CHARS     = int(os.environ.get("AT_MAX_DIFF_CHARS", "12000"))
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
REPO          = os.environ.get("GITHUB_REPOSITORY", "")
SHA           = os.environ.get("GITHUB_SHA", "")
BASE_REF      = os.environ.get("GITHUB_BASE_REF", "main")
HEAD_REF      = os.environ.get("GITHUB_HEAD_REF", "")

PROTOCOL_WALLET = "rmcSrkpZ2i2kuvtCPeTVetee9SixP4djR"
XRPL_NODE       = "https://s1.ripple.com:51234/"

# USDC on Base
USDC_CONTRACT   = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
BASE_RPC        = "https://mainnet.base.org"
USDC_AMOUNT     = 100_000   # $0.10 in 6-decimal USDC units


def set_output(name: str, value: str):
    env_file = os.environ.get("GITHUB_OUTPUT", "")
    if env_file:
        with open(env_file, "a") as f:
            f.write(f"{name}={value}\n")


def fail(message: str):
    print(f"\n::error::{message}")
    sys.exit(1)


def get_diff() -> str:
    """Get the PR diff via git or GitHub API."""
    try:
        result = subprocess.run(
            ["git", "diff", f"origin/{BASE_REF}...HEAD"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            diff = result.stdout.strip()
            if len(diff) > MAX_CHARS:
                diff = diff[:MAX_CHARS] + f"\n\n[diff truncated at {MAX_CHARS} chars]"
            return diff
    except Exception:
        pass

    if not GITHUB_TOKEN or not REPO:
        fail("Could not retrieve PR diff. Ensure actions/checkout runs before this action.")

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
    }
    url = f"https://api.github.com/repos/{REPO}/commits/{SHA}"
    resp = httpx.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        fail(f"GitHub API returned {resp.status_code} fetching diff.")
    diff = resp.text.strip()
    if len(diff) > MAX_CHARS:
        diff = diff[:MAX_CHARS] + f"\n\n[diff truncated at {MAX_CHARS} chars]"
    return diff


def pay_xrp() -> str:
    """Send 0.1 XRP to the protocol wallet. Returns tx hash."""
    if not XRP_SECRET:
        fail("payment_method is 'xrp' but xrp_secret is not set. "
             "Add your XRPL wallet secret as a GitHub Actions secret and pass it via inputs.xrp_secret.")

    wallet = Wallet.from_seed(XRP_SECRET)
    client = JsonRpcClient(XRPL_NODE)

    tx = Payment(
        account=wallet.address,
        amount=xrp_to_drops(0.1),
        destination=PROTOCOL_WALLET,
    )
    response = submit_and_wait(tx, client, wallet)
    if not response.is_successful():
        fail(f"XRP payment failed: {response.result.get('engine_result_message', '')}")

    tx_hash = response.result["hash"]
    print(f"✓ Paid 0.1 XRP — tx hash: {tx_hash}")
    return tx_hash


def pay_usdc() -> str:
    """Send $0.10 USDC on Base. Returns EVM tx hash."""
    if not USDC_KEY:
        fail("payment_method is 'usdc' but usdc_private_key is not set.")

    probe = httpx.post(f"{REFEREE_URL}/audit", json={"task": "probe", "work": "probe"}, timeout=15)
    if probe.status_code != 402:
        fail(f"Expected 402 from /audit probe, got {probe.status_code}.")

    body = probe.json()
    accepts = body.get("accepts", [])
    usdc_entry = next((a for a in accepts if a.get("asset") == "USDC"), None)
    if not usdc_entry:
        fail("USDC payment option not configured on this Referee.")

    pay_to = usdc_entry["payTo"]

    try:
        from eth_account import Account
        import eth_abi
    except ImportError:
        fail("eth-account and eth-abi are required for USDC payments. "
             "Add them to your workflow: pip install eth-account eth-abi")

    account = Account.from_key(USDC_KEY)
    sender  = account.address

    selector = bytes.fromhex("a9059cbb")
    encoded  = eth_abi.encode(["address", "uint256"], [pay_to, USDC_AMOUNT])
    data     = "0x" + (selector + encoded).hex()

    rpc = httpx.post(BASE_RPC, json={"jsonrpc":"2.0","id":1,"method":"eth_getTransactionCount",
        "params":[sender,"latest"]}, timeout=15).json()
    nonce = int(rpc["result"], 16)

    rpc = httpx.post(BASE_RPC, json={"jsonrpc":"2.0","id":2,"method":"eth_gasPrice","params":[]}, timeout=15).json()
    gas_price = int(rpc["result"], 16)

    tx_obj = {
        "to": USDC_CONTRACT, "value": 0, "gas": 80_000,
        "gasPrice": gas_price, "nonce": nonce, "chainId": 8453, "data": data,
    }
    signed = account.sign_transaction(tx_obj)
    rpc = httpx.post(BASE_RPC, json={"jsonrpc":"2.0","id":3,"method":"eth_sendRawTransaction",
        "params":[signed.rawTransaction.hex()]}, timeout=15).json()

    if "error" in rpc:
        fail(f"USDC transfer failed: {rpc['error']['message']}")

    tx_hash = rpc["result"]
    print(f"✓ Paid $0.10 USDC on Base — tx hash: {tx_hash}")
    return tx_hash


def run_audit(diff: str, payment_hash: str) -> dict:
    resp = httpx.post(
        f"{REFEREE_URL}/audit",
        headers={"x-payment-hash": payment_hash},
                json={"task": JOB_SPEC, "work": diff},
        timeout=120,
    )
    if resp.status_code != 200:
        fail(f"Referee returned {resp.status_code}: {resp.text[:400]}")
    return resp.json()


def main():
    print("── AgentTrust AI Audit ──────────────────────")
    print(f"Referee:  {REFEREE_URL}")
    print(f"Payment:  {METHOD.upper()}")
    print(f"Pass if:  score ≥ {THRESHOLD}")
    print()

    print("Fetching PR diff…")
    diff = get_diff()
    print(f"Diff size: {len(diff)} chars")
    print()

    print("Paying audit fee…")
    if METHOD == "xrp":
        payment_hash = pay_xrp()
    elif METHOD == "usdc":
        payment_hash = pay_usdc()
    else:
        fail(f"Unknown payment_method '{METHOD}'. Use 'xrp' or 'usdc'.")

    print()
    print("Submitting to AI referee…")
    result = run_audit(diff, payment_hash)

    verdict = result.get("verdict", "FAIL")
    score   = result.get("score", 0)
    summary = result.get("summary", "")

    set_output("verdict", verdict)
    set_output("score", str(score))
    set_output("summary", summary)
    set_output("payment_hash", payment_hash)

    print()
    print(f"── Result ───────────────────────────────────")
    print(f"Verdict : {verdict}")
    print(f"Score   : {score}/100")
    print(f"Summary : {summary}")
    print()

    if verdict == "PASS" and score >= THRESHOLD:
        print("✓ Audit passed.")
    else:
        reason = f"score {score} < threshold {THRESHOLD}" if score < THRESHOLD else "verdict FAIL"
        fail(f"Audit failed ({reason}). See summary above.")


main()
