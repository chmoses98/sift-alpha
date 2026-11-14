"""Verified, computable input features (RESEARCH_ONLY). One module per sport; a registry of FeatureSpec records declares, for each catalog input, exactly which columns implement it,
how much of its definition is implemented, and which raw datasets it needs. Nothing counts as computed until the audit has executed the builder, measured coverage and passed the leak test."""
