from argon2 import PasswordHasher
""" 

    Created a little program. That encrypts the password and also ads a salt to it.
    Tested the salting with 2 encryptions that are the same, i get 2 different hashes.
    Salting is inside the hash creator.

"""

ph = PasswordHasher() # Creating passwordhasher object
password = 'DutchPirate1650!@#$%'
hashed1 = ph.hash(password) # Hash paswword and auto salt
hashed2 = ph.hash(password) # Hash paswword and auto salt
print(f"Hashed 1: {hashed1}")
print(f"Hashed 2: {hashed2}")



try:
    ph.verify(hashed1, 'DutchPirate1650!@#$%') #checking password = password
    ph.verify(hashed2, 'DutchPirate1650!@#$%') #checking password = password
    print("Verified")
except Exception as e: # Cathing Verify Mismatch
    print(f"Verification failed: {e}")
