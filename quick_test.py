#!/usr/bin/env python3
"""
Quick Test Script - Verify all nodes and endpoints are working
Usage: python quick_test.py
"""

import subprocess
import json
import sys
from pathlib import Path


def test_endpoint(url, expected_status=200):
    """Test a single endpoint"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
            capture_output=False,
            timeout=5
        )
        return True
    except Exception as e:
        return False


def curl_json(url):
    """Get JSON response from endpoint"""
    try:
        result = subprocess.run(
            ["curl", "-s", url],
            capture_output=True,
            text=True,
            timeout=5
        )
        return json.loads(result.stdout)
    except Exception as e:
        return None


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_status(name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {name}")
    if details:
        print(f"       {details}")


def test_node(port):
    """Test a single node"""
    print_header(f"Testing Node on Port {port}")
    
    base_url = f"http://127.0.0.1:{port}"
    all_pass = True
    
    # Test 1: Basic Status
    result = curl_json(f"{base_url}/status")
    passed = result is not None and "chain" in result
    print_status("Basic Status Endpoint", passed)
    all_pass = all_pass and passed
    
    # Test 2: Health Check
    result = curl_json(f"{base_url}/healthz")
    passed = result is not None and "healthy_peers" in result
    print_status("Health Check Endpoint", passed)
    all_pass = all_pass and passed
    
    # Test 3: Peer Health
    result = curl_json(f"{base_url}/peer_health")
    passed = result is not None and isinstance(result, list)
    print_status("Peer Health Endpoint", passed)
    all_pass = all_pass and passed
    
    # Test 4: Deployment Status
    result = curl_json(f"{base_url}/deployment_status")
    passed = result is not None and "rollout_state" in result
    print_status("Deployment Status Endpoint", passed)
    all_pass = all_pass and passed
    
    # Test 5: Launch Readiness
    result = curl_json(f"{base_url}/launch_readiness")
    passed = result is not None and "ready_for_launch" in result
    details = f"Ready: {result.get('ready_for_launch', '?')}" if result else ""
    print_status("Launch Readiness Endpoint", passed, details)
    all_pass = all_pass and passed
    
    # Test 6: Deployment Runbook
    result = curl_json(f"{base_url}/deployment_runbook")
    passed = result is not None and "steps" in result
    details = f"Steps: {len(result.get('steps', []))}" if result else ""
    print_status("Deployment Runbook Endpoint", passed, details)
    all_pass = all_pass and passed
    
    # Test 7: Network Health Dashboard
    result = curl_json(f"{base_url}/network_health_dashboard")
    passed = result is not None and "blockchain" in result and "network" in result
    print_status("Network Health Dashboard", passed)
    all_pass = all_pass and passed
    
    # Test 8: Operations Status
    result = curl_json(f"{base_url}/ops_status")
    passed = result is not None
    print_status("Operations Status Endpoint", passed)
    all_pass = all_pass and passed
    
    # Test 9: Blockchain
    result = curl_json(f"{base_url}/blockchain")
    passed = result is not None and isinstance(result, list) and len(result) > 0
    details = f"Chain Height: {len(result)}" if result else ""
    print_status("Blockchain Endpoint", passed, details)
    all_pass = all_pass and passed
    
    # Test 10: Validators
    result = curl_json(f"{base_url}/validate_chain")
    passed = result is not None and "valid" in result
    details = f"Valid: {result.get('valid', '?')}" if result else ""
    print_status("Validate Chain Endpoint", passed, details)
    all_pass = all_pass and passed
    
    return all_pass


def main():
    print("\n" + "="*60)
    print("  🧪 KawaidCoin Testnet - Quick Test Suite")
    print("="*60)
    
    results = {}
    
    # Test Main Node
    results["Main Node (5000)"] = test_node(5000)
    
    # Test Node 2
    results["Node 2 (5001)"] = test_node(5001)
    
    # Summary
    print_header("Summary")
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} | {name}")
    
    all_pass = all(results.values())
    
    if all_pass:
        print("\n" + "="*60)
        print("  ✅ ALL TESTS PASSED - Nodes are ready!")
        print("="*60)
        return 0
    else:
        print("\n" + "="*60)
        print("  ❌ SOME TESTS FAILED - Check connectivity")
        print("="*60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
