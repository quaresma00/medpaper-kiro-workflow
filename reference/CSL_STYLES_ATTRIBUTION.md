# Citation Style Language styles - attribution

`reference/csl_issn_index.json` is derived from the Citation Style Language (CSL) style
repository, <https://github.com/citation-style-language/styles> (branch `v1.0.2`), by the
Citation Style Language project and its contributors - <https://citationstyles.org>.

The styles and data derived from them are licensed under the
[Creative Commons Attribution-ShareAlike 3.0 Unported license (CC BY-SA 3.0)](https://creativecommons.org/licenses/by-sa/3.0/).
The index (ISSN -> dependent style id -> independent parent style id) is distributed under the
same license. Changes made: only the `<id>`, `<issn>`, `<eissn>` and `independent-parent` link
of each style were read and rearranged into a lookup table; no style was modified.

Regenerate (maintainer only; the one command that uses the network for this):

    .venv\Scripts\python.exe tools/refs/csl_index.py build

Style files themselves are fetched at runtime from the same branch
(`tools/refs/csl_index.py fetch --issn <ISSN>`) and keep their own license headers.
