# Third party notices

DreamSeed vendors Cubiomes at commit `e61f90580cbdd883214a8054670dacae655e59c0`.
Cubiomes is Copyright 2020 Cubitect and is distributed under the MIT License.
Its license is preserved at `third_party/cubiomes/LICENSE`.
The experimental Metal placement kernel derives its placement arithmetic from
Cubiomes and is covered by the same preserved upstream notice.

The build fetches nlohmann JSON commit
`9cca280a4d0ccf0c08f47a99aa71d1b0e52f8d03`, which is release 3.11.3. It is
distributed under the MIT License. Its source and license are available from
its upstream release.

The Python environment installs the official MCP SDK 2.2.0 and Pydantic
2.12.5. Both are distributed under the MIT License, and their license files
are installed with their Python packages.

Minecraft server software is not included in DreamSeed distributions. The
optional setup command downloads an explicitly selected pinned Java server from
Mojang after explicit user acceptance. Its use is governed by the Minecraft
EULA at https://www.minecraft.net/en-us/eula.
Optional template validation reads Minecraft's own igloo templates from that
installed server. No template files, bytecode, or complete worlds are bundled.
