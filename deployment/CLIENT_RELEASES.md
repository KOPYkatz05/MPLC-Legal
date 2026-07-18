# Client installer and update-feed build

`build_client_release.ps1` turns the existing PyInstaller `onedir` client into
a per-user Velopack installer plus a static update feed. It does not upload or
publish anything.

The release identity is deliberately centralized in `client_release.json`:

- package ID: `MissionLegal.MissionLegalTracker`
- main executable: `MissionLegal.exe`
- default channel: `stable`
- target runtime: `win-x64`
- pinned Python SDK / `vpk` CLI version: `1.2.0`

Do not change the package ID after distributing the first installer. Velopack
uses it for the installation root and update identity.

## First release

Build the PyInstaller client for the version in `version.py`, then package it:

```powershell
.\deployment\build_windows.ps1 -Target Client
.\deployment\build_client_release.ps1 `
  -InstallVpk `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/'
```

`-InstallVpk` downloads the official NuGet tool package, verifies its pinned
SHA-256, and installs the exact CLI under the ignored `build\tools\velopack`
directory. It needs the .NET 8 runtime, not the .NET SDK. Later runs locate that
copy automatically. You may instead supply an exact pinned executable with
`-VpkPath`.

`-UpdateUrl` is required because it is embedded beside `MissionLegal.exe` as
`mission-legal-update.json`. The URL must be the public HTTPS directory that
will contain `releases.stable.json` and the packages. As an alternative, set
`MISSION_LEGAL_RELEASE_UPDATE_URL` on the release machine. Credentials, query
tokens, and fragments are rejected. For a public GitHub repository, also pass
`-UpdateProvider github`; the default is a provider-neutral static HTTP feed.

The static-host-ready result is written to:

```text
dist\client-releases\stable\
  MissionLegal.MissionLegalTracker-stable-Setup.exe
  MissionLegal.MissionLegalTracker-<version>-stable-full.nupkg
  releases.stable.json
  assets.stable.json
```

Upload the entire directory without renaming individual files. The update URL
used by the client is the directory URL, not the JSON file URL.

## First run on another computer

The installed Start menu/Desktop shortcut opens `MissionLegal.exe`. If that
Windows user has not been paired yet, the app opens a first-run connection
window automatically. The user enters:

- the main computer's HTTPS address, such as `https://MAIN-COMPUTER:8765`;
- the public `mission-legal-ca.pem` certificate copied from the main computer;
- a six-digit one-use pairing code from the administrator; and
- a recognizable name for that computer.

The app copies only the public CA certificate into the user's stable LocalAppData
configuration and stores the device credential in Windows Credential Manager.
It does not create a local writable database. `MissionLegalClientSetup.exe`
remains available as a command-line pairing option for automated deployment,
but normal users do not need to find or run it.

## Later releases and deltas

Keep the same output directory across versions. If it still contains the prior
full package, `vpk pack` creates a delta automatically. A clean release machine
can seed the prior package from a static HTTPS feed:

```powershell
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -PreviousReleaseUrl 'https://updates.example.org/mission-legal/client/'
```

For a public GitHub Releases source, use the repository URL for both values.
`PreviousReleaseProvider` defaults to `UpdateProvider`, so the matching GitHub
download command is selected without a token:

```powershell
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://github.com/OWNER/REPOSITORY' `
  -UpdateProvider github `
  -PreviousReleaseUrl 'https://github.com/OWNER/REPOSITORY'
```

`-PreviousReleaseProvider github` can be supplied explicitly when the previous
source differs from the embedded update provider. Only public, secret-free
repository URLs are accepted; release credentials are not embedded in the app.

## Raw-package provenance

`build_windows.ps1 -Target Client` writes
`dist\<version>\MissionLegalClient.provenance.json` beside the raw
`MissionLegalClient` directory. `build_client_release.ps1` refuses to package a
folder unless that manifest exactly matches the requested version, client role,
current API/schema versions, current Git source and dependency locks, successful
frozen smoke result, executable Windows versions, OCR model trees, and every
file's size and SHA-256.

The default input discovers that sibling automatically. For another verified
raw folder, keep its sibling manifest with it or pass both explicitly:

```powershell
.\deployment\build_client_release.ps1 `
  -Version '0.2.0' `
  -InputDir 'D:\staging\MissionLegalClient' `
  -ProvenanceManifestPath 'D:\staging\MissionLegalClient.provenance.json' `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/'
```

Do not edit the raw folder or reuse it under another version. The release script
temporarily overlays its validated, secret-free `mission-legal-update.json` only
while `vpk` reads the folder, restores the exact raw input afterward, and
re-verifies provenance. Any other change requires a new raw client build.

It can also seed from a local directory or network share:

```powershell
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -PreviousReleaseDirectory 'D:\published\mission-legal-client'
```

The script fails if the same version already exists. Increment `APP_VERSION`
before every release; published packages are immutable.

In production, history is mandatory: unless `-InitialRelease` is explicit, the
builder defaults `PreviousReleaseUrl` to `UpdateUrl`, downloads the published
history, and requires the candidate version to be strictly newer. This prevents
a clean build machine from accidentally replacing a channel with a history-free
feed. Use `-InitialRelease` only once; it rejects local assets and also probes
the published HTTP/GitHub source for prior assets before packing.

The compatibility constants in `version.py` are independent release controls.
Do not raise `MIN_SUPPORTED_CLIENT_VERSION` merely because a newer client is
available. Raise it only when older clients are genuinely unsafe or
incompatible; doing so turns the normal optional update into a required update
before that client can connect to the server.

## Signing

Unsigned builds are suitable only for local installer testing. Production
releases should use `-RequireSigning` plus one supported Velopack signing mode.
`-RequireSigning` also requires the raw-package provenance to come from a clean
Git commit; commit the intended release source and rebuild the client first.

For a certificate already available to `signtool.exe`:

```powershell
$env:MISSION_LEGAL_VPK_SIGN_PARAMS = '/sha1 CERT_THUMBPRINT /fd sha256 /td sha256 /tr https://timestamp.example'
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -ExpectedSignerThumbprint 'CERTIFICATE_SHA1_THUMBPRINT' `
  -RequireSigning
```

Or use Azure Trusted Signing metadata:

```powershell
.\deployment\build_client_release.ps1 `
  -UpdateUrl 'https://updates.example.org/mission-legal/client/' `
  -AzureTrustedSignFile 'C:\signing\metadata.json' `
  -ExpectedSignerThumbprint 'CERTIFICATE_SHA1_THUMBPRINT' `
  -RequireSigning
```

`-SignTemplate` is available for another signing tool. Use absolute paths in
signing arguments. `ExpectedSignerThumbprint` is the signing certificate's
40-hex SHA-1 thumbprint as Windows reports it; it selects the expected identity,
while artifact integrity is still recorded and checked with SHA-256. Production
validation requires a trusted timestamp and that same signer on Setup,
`MissionLegal.exe`, the update worker, execution stub, diagnostics, and pairing
helper inside the full package.

## Validation and publishing boundary

The script validates that:

- the raw input and sibling provenance exactly match the requested client role,
  version, source, dependency locks, smoke result, PE versions, OCR models, and
  complete package tree;
- the input contains `MissionLegal.exe` and no database, SQLite sidecar, or
  private-key files;
- `mission-legal-update.json` is written as secret-free UTF-8 beside the executable;
- input and output directories do not overlap;
- the feed contains exactly one full package for the requested version;
- every feed entry names an existing, non-empty file without path traversal;
- current package sizes and available SHA-1/SHA-256 values match the feed;
- a delta exists whenever a previous full release was available;
- the per-user installer exists and, when signing is enabled, is validly signed.

Packing occurs in a unique sibling transaction directory. Existing feed files
are cloned there for delta generation, and the final channel directory is
replaced only after the complete staged feed validates. A failed or interrupted
pack therefore cannot mix partial new files into the current feed; the next run
repairs an interrupted directory swap while holding an exclusive release lock.

Revalidate an already-built static directory without running `vpk`:

```powershell
.\deployment\build_client_release.ps1 -ValidateOnly
```

Run the isolated wrapper fixture test with:

```powershell
.\deployment\test_client_release_packaging.ps1
```

Run a real installed update against a loopback-only copy of a two-version feed:

```powershell
.\deployment\test_installed_client_update.ps1 `
  -BaselineInstaller '.\dist\update-test\MissionLegal-0.1.0-Setup.exe' `
  -FeedDirectory '.\dist\update-test\feed' `
  -BaselineVersion '0.1.0' `
  -ExpectedVersion '0.1.1'
```

The baseline installer must be saved before packaging the second version; the
stable setup inside the feed always installs the newest version. The harness
refuses artifacts outside this repository or an existing per-user Mission
Legal installation. It installs below `build\tests`, binds the static feed only
to `127.0.0.1`, exercises the guarded frozen-app update probe, then always stops
the feed, invokes Velopack uninstall, and removes the isolated installation.
It requires the expected release to be the newest feed version and, by default,
requires and verifies its delta package. Small diagnostic logs remain in the
ignored `build\tests\installed-client-update` directory.

For a fast non-installing validation, add `-ValidateOnly`. The harness's own
path-containment, version-ordering, hash, and traversal contract test is:

```powershell
.\deployment\test_installed_client_update_harness.ps1
```

Before publishing, install on a clean standard-user Windows account and test an
upgrade from the prior release. Hosting and upload credentials intentionally do
not live in this repository.

For a static HTTPS host, publish a release transaction in this order:

1. upload the new versioned full and delta `.nupkg` files;
2. upload the latest setup executable and `assets.stable.json`;
3. verify those uploaded objects by size/hash from outside the build folder;
4. upload `releases.stable.json` last, because that feed makes the new update
   visible to installed clients.

Never expose a feed entry before every package it references is available. For
GitHub Releases, keep the release as a draft until every asset is uploaded and
verified, then publish it as one operator action.

After `releases.stable.json` is live, perform the read-only outside-the-build
verification against the immutable summary created by `build_release.ps1`:

```powershell
.\deployment\verify_published_client_feed.ps1 `
  -FeedBaseUrl 'https://updates.example.org/mission-legal/client/' `
  -ReleaseSummaryPath '.\dist\<version>\release-metadata\release-summary.json' `
  -ExpectedSignerThumbprint 'CERTIFICATE_SHA1_THUMBPRINT'
```

The verifier follows no redirects and performs only HTTPS GET requests. It
requires the published JSON and packages to match the summary by size/SHA-256,
then rechecks timestamped Setup and inner executable signatures. A successful
result has `remote_mutations_performed: false`.

When a server release raises `MIN_SUPPORTED_CLIENT_VERSION`, publish and verify
the compatible client release first. Only then deploy the server installer;
otherwise older clients can be required to download a version that the public
feed does not yet offer.
