# OrcaSlicer plugin integration direction

Recorded 2026-10-16 following review of OrcaSlicer 2.5.0 alpha and the
[Orca Cloud Plugin Hub](https://cloud.orcaslicer.com/app/plugins/plugin-hub).
The version discussed was 2.5.0 alpha, not 1.5 alpha.

## Recommendation

Trial the alpha alongside the stable production workflow, with backed-up
profiles and representative projects. Treat plugins as an integration
opportunity for this repository, not evidence that its experimental quality
transformations improve physical prints.

Keep the optimizer core independent of Orca: retain the CLI, modal parser,
validation, explicit opt-in transformations, and reproducible control/test
outputs. Start any integration with a thin plugin adapter exposing existing
diagnostics and transformations. Do not rewrite the core around an alpha API.

Investigate deeper slicing hooks later for geometry and cross-layer work.
Structured slicing data could reduce dependence on reconstructing intent from
exported G-code, but the exact data and mutation guarantees available to plugins
must be verified before changing the architecture. Plugin integration does not
resolve unknown firmware macro state or replace physical validation.

## Verified release capabilities

The official 2.5.0 alpha release, published October 16, 2026, introduces:

- Python plugins using a runtime bundled with OrcaSlicer.
- Script actions, custom tabs/panels, lifecycle events, and slicing pipeline
  hooks, including exported G-code post-processing.
- Plugin configuration overrides attached to presets and carried with projects
  and cloud sync.
- Local plugin installation for private development, plus Orca Cloud
  subscriptions, installation across signed-in computers, and update offers.

The plugin API may change. Permission prompts cover operations such as external
file access, network access, and launching programs; the release explicitly
describes this as a permission system, not a sandbox.

Source: [Official 2.5.0 alpha release notes](https://github.com/OrcaSlicer/OrcaSlicer/releases/tag/v2.5.0-alpha).

## Limits of the review

The Plugin Hub redirected to sign-in, so individual plugins, their quality,
and catalog maturity were not assessed. No alpha build or plugin was installed,
and no slicing or print comparison was performed.

Speed Dial and texture displacement are useful-looking additions, but plugin
integration is the release's main architectural opportunity for this project.

## Next implementation step

When integration work is requested, verify the current plugin API and build a
minimal local adapter around existing diagnostics first. Check no-op output
integrity, configuration mapping, error handling, and processing order before
exposing behavior-changing passes. Continue controlled physical A/B testing as
the evidence gate for print-quality claims.
