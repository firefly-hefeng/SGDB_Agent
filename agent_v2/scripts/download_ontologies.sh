#!/bin/bash
# Download ontology files from OBO Foundry

set -e

ONTOLOGY_DIR="$(dirname "$0")/../data/ontologies"
mkdir -p "$ONTOLOGY_DIR"

echo "============================================"
echo "  Downloading Ontology Files"
echo "============================================"
echo

# UBERON - Anatomy/Tissue ontology
echo "Downloading UBERON (anatomy)..."
wget -q --show-progress -O "$ONTOLOGY_DIR/uberon.obo" \
    http://purl.obolibrary.org/obo/uberon.obo
echo "✓ UBERON downloaded"
echo

# MONDO - Disease ontology
echo "Downloading MONDO (disease)..."
wget -q --show-progress -O "$ONTOLOGY_DIR/mondo.obo" \
    http://purl.obolibrary.org/obo/mondo.obo
echo "✓ MONDO downloaded"
echo

# CL - Cell Ontology
echo "Downloading CL (cell types)..."
wget -q --show-progress -O "$ONTOLOGY_DIR/cl.obo" \
    http://purl.obolibrary.org/obo/cl.obo
echo "✓ CL downloaded"
echo

# EFO - Experimental Factor Ontology (includes assays)
echo "Downloading EFO (experimental factors)..."
wget -q --show-progress -O "$ONTOLOGY_DIR/efo.obo" \
    http://purl.obolibrary.org/obo/efo.obo
echo "✓ EFO downloaded"
echo

echo "============================================"
echo "  Download Complete"
echo "============================================"
echo
ls -lh "$ONTOLOGY_DIR"/*.obo
