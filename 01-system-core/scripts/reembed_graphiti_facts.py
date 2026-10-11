"""用 bge-m3 重嵌入 Neo4j 中所有 RELATES_TO 的 fact_embedding 与 Entity 的 name_embedding。

之前 PoC 用 stub blake2b 伪向量写入，切到真实 embedder 后必须刷新。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer


def main() -> None:
    cfg_path = ROOT / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # 不需要 LLM，只做向量重算
    uri = "bolt://localhost:7687"
    user = "neo4j"
    pw = "moxi_pass_2026"

    print(f"[reembed] loading bge-m3 ...")
    model = SentenceTransformer("BAAI/bge-m3")

    def encode(texts: list[str]) -> list[list[float]]:
        arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [[float(x) for x in row] for row in arr]

    drv = GraphDatabase.driver(uri, auth=(user, pw))
    with drv.session() as s:
        edges = s.run(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.fact IS NOT NULL "
            "RETURN r.uuid AS uuid, r.fact AS fact"
        ).data()
        print(f"[reembed] edges to update: {len(edges)}")
        if edges:
            texts = [e["fact"] for e in edges]
            vecs = encode(texts)
            for e, v in zip(edges, vecs):
                s.run(
                    "MATCH ()-[r:RELATES_TO {uuid: $uuid}]->() "
                    "SET r.fact_embedding = $vec",
                    uuid=e["uuid"], vec=v,
                )
            print(f"[reembed] edges done")

        nodes = s.run(
            "MATCH (n:Entity) WHERE n.name IS NOT NULL "
            "RETURN n.uuid AS uuid, coalesce(n.summary, n.name) AS text"
        ).data()
        print(f"[reembed] entity nodes to update: {len(nodes)}")
        if nodes:
            texts = [n["text"] for n in nodes]
            vecs = encode(texts)
            for n, v in zip(nodes, vecs):
                s.run(
                    "MATCH (n:Entity {uuid: $uuid}) SET n.name_embedding = $vec",
                    uuid=n["uuid"], vec=v,
                )
            print(f"[reembed] entity nodes done")

    drv.close()
    print("[reembed] OK")


if __name__ == "__main__":
    main()
