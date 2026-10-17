import { studioTheme } from "ag-studio";

// Countersign's own palette (the same tokens the main page uses), dark first
export const palette = {
  bg: "#04050d", ink: "#f0f2ff", muted: "#a3acd6", faint: "#6770a0", line: "#8c9eff2e",
  allow: "#3df5c4", hold: "#ffc94d", refuse: "#ff5f84", a1: "#6a82ff", a2: "#c866ff", a3: "#2fd9ff", a4: "#ff6bb5",
};

// the order a chart uses its colours in: the blue first, then red for what was lost, then green, amber, violet, cyan
const series = ["#6a82ff", palette.refuse, palette.allow, palette.hold, palette.a2, palette.a3, palette.a4];
const chartColours = Object.fromEntries(series.flatMap((c, i) => [[`chartPaletteFills${i + 1}Color`, c], [`chartPaletteStrokes${i + 1}Color`, c]]));

const shared = {
  ...chartColours,
  fontFamily: '"Figtree", "Segoe UI", sans-serif',
  accentColor: palette.a1,
  borderRadius: 10,
};

export const darkTheme = studioTheme.withParams(
  {
    ...shared,
    backgroundColor: "#0b0e24",
    foregroundColor: palette.ink,
    textColor: palette.ink,
    borderColor: palette.line,
    chromeBackgroundColor: "#0b0e24",
    studioCanvasBackgroundColor: palette.bg,
    studioWidgetBackgroundColor: "#10143280",
    studioWidgetBorderRadius: 14,
    studioWidgetTitleFontFamily: '"Bricolage Grotesque", "Segoe UI", sans-serif',
    studioWidgetTitleFontSize: 15,
    studioWidgetTitleTextColor: palette.muted,
  } as never,
  "dark",
);

export const lightTheme = studioTheme.withParams(
  {
    ...shared,
    accentColor: "#4259e6",
    studioCanvasBackgroundColor: "#f5f1e8",
    studioWidgetTitleFontFamily: '"Bricolage Grotesque", "Segoe UI", sans-serif',
    studioWidgetTitleFontSize: 15,
  } as never,
  "light",
);
