"""FTS index over Chinese bigrams, so large libraries do not load into RAM."""
import re


def tokens(text):
    values = re.findall(r'[a-zA-Z0-9_]+|[\u3400-\u9fff]+', text.lower())
    output = []
    for value in values:
        if re.search(r'[\u3400-\u9fff]', value):
            output.extend(value[i:i+2] for i in range(max(1,len(value)-1)))
        else:
            output.append(value)
    return output


def initialize(store):
    with store.connect() as db:
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_search USING fts5(document_id UNINDEXED, title UNINDEXED, chunk_id UNINDEXED, page UNINDEXED, excerpt UNINDEXED, terms)')
        existing = {row[0] for row in db.execute('SELECT DISTINCT document_id FROM knowledge_search')}
    for doc in store.iter('documents'):
        if doc['id'] not in existing:
            with store.connect() as db:
                index_document(db, doc)


def index_document(db, doc):
    db.execute('DELETE FROM knowledge_search WHERE document_id=?', (doc['id'],))
    db.executemany('INSERT INTO knowledge_search(document_id,title,chunk_id,page,excerpt,terms) VALUES(?,?,?,?,?,?)',
        ((doc['id'],doc['title'],chunk['id'],chunk.get('page',''),chunk['text'],' '.join(tokens(chunk['text']))) for chunk in doc['chunks']))


def search(store, text):
    terms = list(dict.fromkeys(tokens(text)))[:80]
    if not terms:
        return []
    query = ' OR '.join('"'+word.replace('"','""')+'"' for word in terms)
    with store.connect() as db:
        rows = db.execute('SELECT document_id,title,chunk_id,page,excerpt,bm25(knowledge_search) AS rank FROM knowledge_search WHERE knowledge_search MATCH ? ORDER BY rank LIMIT 4', (query,)).fetchall()
    return [{'document_id':row['document_id'],'title':row['title'],'chunk_id':int(row['chunk_id']),'page':row['page'],'text':row['excerpt'],'score':-row['rank']} for row in rows]


def summaries(store):
    with store.connect() as db:
        rows = db.execute("SELECT id,json_extract(data,'$.title') AS title,substr(json_extract(data,'$.text'),1,1200) AS preview,length(json_extract(data,'$.text')) AS chars,json_array_length(json_extract(data,'$.chunks')) AS chunks,json_extract(data,'$.created_at') AS created_at,json_extract(data,'$.ocr.ocr_pages') AS ocr_pages,json_extract(data,'$.ocr.low_confidence_lines') AS low_lines,json_extract(data,'$.ocr.warnings') AS warnings FROM documents ORDER BY rowid DESC").fetchall()
    import json
    return [{'id':row['id'],'title':row['title'],'text':row['preview'],'char_count':row['chars'],'chunk_count':row['chunks'],'created_at':row['created_at'],
             'ocr':{'ocr_pages':row['ocr_pages'] or 0,'low_confidence_lines':row['low_lines'] or 0,'warnings':json.loads(row['warnings'] or '[]')}} for row in rows]
