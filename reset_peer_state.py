from pathlib import Path

root = Path(r'C:\Users\MD khalid\Desktop\2026 blockchain')
for rel in ['blacklisted_peers.json', 'peer_failures.json', 'peer_reputations.json']:
    path = root / rel
    if rel == 'blacklisted_peers.json':
        path.write_text('[]', encoding='utf-8')
    else:
        path.write_text('{}', encoding='utf-8')
    print(f'cleared {rel}')
