from mine_block import main

if __name__ == "__main__":
    main()

).hexdigest()

new_block["hash"] = block_hash

chain.append(new_block)

with open("blockchain_data.json", "w") as f:
    json.dump(chain, f, indent=4)

with open("mempool.json", "w") as f:
    json.dump([], f, indent=4)

print("BLOCK MINED")
print("BLOCK INDEX:", new_block["index"])
print("HASH:", block_hash)