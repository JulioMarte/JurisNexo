# datasets

Owns dataset definitions and immutable/frozen dataset snapshots over the canonical corpus.

A dataset is a logical, reproducible selection of canonical document IDs plus manifest/version metadata. It is not a copied folder of PDFs. One canonical document may belong to many snapshots without duplicating its S3 artifact.
