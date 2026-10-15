// Thin line icons (drawn here, no icon library needed).
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  viewBox: "0 0 24 24",
};

export const HangerIcon = (p) => (
  <svg {...base} {...p}><path d="M12 7.5a2 2 0 1 0-2-2" /><path d="M12 7.5v1.2L3.2 15a1.5 1.5 0 0 0 .9 2.7h15.8a1.5 1.5 0 0 0 .9-2.7L12 8.7" /></svg>
);
export const HomeIcon = (p) => (
  <svg {...base} {...p}><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V20h5v-6h4v6h5V9.5" /></svg>
);
export const SparkleIcon = (p) => (
  <svg {...base} {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4" /><path d="m7 7 2 2M15 15l2 2M17 7l-2 2M9 15l-2 2" /></svg>
);
export const TrendIcon = (p) => (
  <svg {...base} {...p}><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg>
);
export const CalendarIcon = (p) => (
  <svg {...base} {...p}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
);
export const PlaneIcon = (p) => (
  <svg {...base} {...p}><path d="M10.5 13.5 3 11l1.5-1.5 8 1 4-4a2 2 0 0 1 3 3l-4 4 1 8L15 23l-2.5-7.5" /><path d="m5 17 2 2" /></svg>
);
export const TryOnIcon = (p) => (
  <svg {...base} {...p}><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="12" cy="10" r="3" /><path d="M6.5 19a5.5 5.5 0 0 1 11 0" /></svg>
);
export const SearchIcon = (p) => (
  <svg {...base} {...p}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></svg>
);
export const GearIcon = (p) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>
);
export const LogoutIcon = (p) => (
  <svg {...base} {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></svg>
);
export const PlusIcon = (p) => (
  <svg {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>
);
export const CameraIcon = (p) => (
  <svg {...base} {...p}><path d="M4 8h3l1.6-2.4A1.5 1.5 0 0 1 9.9 5h4.2a1.5 1.5 0 0 1 1.3.6L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z" /><circle cx="12" cy="13" r="3.6" /></svg>
);
export const GalleryIcon = (p) => (
  <svg {...base} {...p}><rect x="3" y="4" width="18" height="16" rx="2.5" /><circle cx="9" cy="9.5" r="1.6" /><path d="m3.5 17 5-5 4 4 2.5-2.5L21 18" /></svg>
);
export const RotateIcon = (p) => (
  <svg {...base} {...p}><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></svg>
);
export const CropIcon = (p) => (
  <svg {...base} {...p}><path d="M6 2v14a2 2 0 0 0 2 2h14" /><path d="M2 6h14a2 2 0 0 1 2 2v14" /></svg>
);
export const CloseIcon = (p) => (
  <svg {...base} {...p}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
export const CheckIcon = (p) => (
  <svg {...base} {...p}><path d="m4.5 12.5 4.5 4.5L19.5 7" /></svg>
);
export const MoreIcon = (p) => (
  <svg {...base} {...p}><circle cx="5" cy="12" r="1.3" /><circle cx="12" cy="12" r="1.3" /><circle cx="19" cy="12" r="1.3" /></svg>
);
export const HeartIcon = ({ filled, ...p }) => (
  <svg {...base} {...p} fill={filled ? "currentColor" : "none"}><path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10Z" /></svg>
);
export const RetakeIcon = (p) => (
  <svg {...base} {...p}><path d="M4 12a8 8 0 0 1 13.7-5.6L20 9" /><path d="M20 4v5h-5" /><path d="M20 12a8 8 0 0 1-13.7 5.6L4 15" /><path d="M4 20v-5h5" /></svg>
);
export const MenuIcon = (p) => (
  <svg {...base} {...p}><path d="M4 7h16M4 12h16M4 17h16" /></svg>
);
