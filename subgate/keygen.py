"""Generate an encryption key locally without writing it to disk."""
from cryptography.fernet import Fernet

if __name__ == '__main__':
    print(Fernet.generate_key().decode())
