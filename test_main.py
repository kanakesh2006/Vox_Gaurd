import pytest
from fastapi.testclient import TestClient
from main import app, extract_amount

client = TestClient(app)

def test_read_main():
    response = client.get("/")
    assert response.status_code == 200

def test_extract_amount():
    assert extract_amount("transfer 500 rupees") == 500.0
    assert extract_amount("send 10,000 to John") == 10000.0
    assert extract_amount("hello") is None
