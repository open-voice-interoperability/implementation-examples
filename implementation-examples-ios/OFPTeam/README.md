# OFPTeam

Native iOS app scaffold using SwiftUI with an MVVM-friendly structure and no external dependencies.

## Project structure

```text
OFPTeam/
├─ OFPTeam.xcodeproj/
└─ OFPTeam/
   ├─ App/
   │  └─ OFPTeamApp.swift
   ├─ Features/
   │  └─ Home/
   │     ├─ Models/
   │     │  └─ HomeState.swift
   │     ├─ ViewModels/
   │     │  └─ HomeViewModel.swift
   │     └─ Views/
   │        └─ HomeView.swift
   ├─ Resources/
   │  └─ Assets.xcassets/
   └─ Preview Content/
      └─ Preview Assets.xcassets/
```

## Open in Xcode

1. On macOS, open Finder and navigate to this folder.
2. Double-click `OFPTeam.xcodeproj`, or run:
   ```bash
   open OFPTeam.xcodeproj
   ```

## Run on Simulator

1. In Xcode, select the `OFPTeam` scheme.
2. Choose an iOS Simulator device (for example, iPhone 16).
3. Press **Run** (`⌘R`).

## Run on a physical device

1. Connect your iPhone or iPad and trust the computer.
2. In Xcode, select your device from the run destination list.
3. Open target **Signing & Capabilities** and choose your Apple Developer Team.
4. Use a unique bundle identifier if prompted.
5. Press **Run** (`⌘R`) and allow Developer Mode on the device if requested.

## Notes

- The initial screen is a placeholder `HomeView` powered by `HomeViewModel`.
- Deployment target is iOS 16.0.
- No third-party libraries are used.
