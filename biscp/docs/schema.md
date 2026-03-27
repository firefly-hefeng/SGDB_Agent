# Data Schema

## Study Object

```json
{
  "accession": "SCP10",
  "name": "string",
  "description": "string",
  "full_description": "string (HTML)",
  "public": true,
  "detached": false,
  "species": "Homo sapiens",
  "species_common": "human",
  "cell_count": 430,
  "gene_count": 5948,
  "study_files": [
    {
      "name": "string",
      "file_type": "string",
      "description": "string",
      "bucket_location": "string",
      "upload_file_size": 12345,
      "download_url": "string",
      "media_url": "string"
    }
  ],
  "directory_listings": [],
  "external_resources": [
    {
      "title": "string",
      "url": "string",
      "description": "string"
    }
  ],
  "publications": [
    {
      "title": "string",
      "journal": "string",
      "url": "string",
      "pmcid": "string",
      "pmid": "string",
      "doi": "string",
      "citation": "string",
      "preprint": false
    }
  ]
}
```

## Field Types

| Field | Type | Nullable |
|-------|------|----------|
| accession | string | no |
| name | string | no |
| description | string | yes |
| full_description | string | yes |
| public | boolean | no |
| detached | boolean | no |
| species | string | yes |
| cell_count | integer | yes |
| gene_count | integer | yes |
| study_files | array | no (may be empty) |
| directory_listings | array | no (may be empty) |
| external_resources | array | no (may be empty) |
| publications | array | no (may be empty) |
