import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_api():
    print("Testing OceanGuard API endpoints...")
    
    # Test Categories
    res = requests.get(f"{BASE_URL}/api/categories")
    assert res.status_code == 200, f"Categories failed: {res.text}"
    print("✅ GET /api/categories passed - Categories:", len(res.json()['categories']))
    
    # Test Reports
    res = requests.get(f"{BASE_URL}/api/reports")
    assert res.status_code == 200, f"Reports failed: {res.text}"
    reports = res.json()['reports']
    print("✅ GET /api/reports passed - Reports count:", len(reports))
    
    # Test Analytics
    res = requests.get(f"{BASE_URL}/api/analytics/stats")
    assert res.status_code == 200, f"Analytics failed: {res.text}"
    stats = res.json()
    print("✅ GET /api/analytics/stats passed - Total reports:", stats['total_reports'], "Verification rate:", stats['verification_rate'])
    
    # Test Login
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"login": "admin", "password": "admin123"})
    assert res.status_code == 200, f"Login failed: {res.text}"
    print("✅ POST /api/auth/login passed - User:", res.json()['user']['full_name'], "Role:", res.json()['user']['role'])
    
    # Test Users (Admin)
    res = requests.get(f"{BASE_URL}/api/users")
    assert res.status_code == 200, f"Users failed: {res.text}"
    print("✅ GET /api/users passed - Users count:", len(res.json()['users']))

    print("\n🎉 ALL REST API TESTS PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_api()
