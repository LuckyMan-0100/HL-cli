import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# Private key bytes from your C++ log (hex decoded)
private_key_hex = "8fcee6f626ca69777eb39f3225049e25bda1b2e0f965d228b0f214341effd79d"
private_key_bytes = bytes.fromhex(private_key_hex)

# Message to sign from your C++ log (from the LATEST run)
message_to_sign_str = "instruction=subscribe&timestamp=1747682182576&window=5000"
message_bytes = message_to_sign_str.encode('utf-8')

# Load the private key
private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_key_bytes)

# Sign the message
signature_bytes = private_key.sign(message_bytes)

# Base64 encode the signature
signature_base64_python = base64.b64encode(signature_bytes).decode('utf-8')

# The signature your C++ code produced in the LATEST run
signature_base64_cpp = "DoYbflUlz32d+4RLpKyYZQT3L1vlyjaqCh3+omhj7hbLXtOrif3TFllDd1ifg9ZrIP32zPvBXRBT8wSmjCM1Ag=="

print(f"Message: {message_to_sign_str}")
print(f"Private Key Hex: {private_key_hex}")
print(f"C++ Generated Signature (Base64):   {signature_base64_cpp}")
print(f"Python Generated Signature (Base64): {signature_base64_python}")

if signature_base64_cpp == signature_base64_python:
    print("\\nSignatures MATCH!")
else:
    print("\\nSignatures DO NOT MATCH.")