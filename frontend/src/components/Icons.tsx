import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement> & { size?: number };
const base = (size = 18): SVGProps<SVGSVGElement> => ({
  width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round",
});
const mk = (paths: JSX.Element) => ({ size, ...p }: P) => <svg {...base(size)} {...p}>{paths}</svg>;

export const ISearch = mk(<><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>);
export const IPin = mk(<><path d="M12 21s-7-6.1-7-11.5A7 7 0 0 1 19 9.5C19 14.9 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></>);
export const ICar = mk(<><path d="M5 17h14v-4.5l-1.8-4.6A2 2 0 0 0 15.3 6.5H8.7a2 2 0 0 0-1.9 1.4L5 12.5z" /><path d="M5 12.5h14" /><circle cx="8" cy="17" r="1.6" /><circle cx="16" cy="17" r="1.6" /></>);
export const IWalk = mk(<><circle cx="13" cy="4" r="1.8" /><path d="m9 21 2.5-6.5L14 17v4" /><path d="M7.5 11.5 10 8l3.5-.8 2.5 3.3 2.5 1" /><path d="m11.5 14.5.9-4.4" /></>);
export const ICrosshair = mk(<><circle cx="12" cy="12" r="8" /><path d="M12 2v4M12 18v4M2 12h4M18 12h4" /></>);
export const ILocate = mk(<><path d="M3 11 21 3l-8 18-2-8z" /></>);
export const ILayers = mk(<><path d="m12 3 9 5-9 5-9-5z" /><path d="m3 13 9 5 9-5" /></>);
export const ISun = mk(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const IMoon = mk(<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />);
export const IShield = mk(<><path d="M12 3 4.5 6v6c0 4.5 3.2 7.8 7.5 9 4.3-1.2 7.5-4.5 7.5-9V6z" /><path d="m9 12 2 2 4-4" /></>);
export const IX = mk(<path d="M6 6l12 12M18 6 6 18" />);
export const ICheck = mk(<path d="m5 12.5 4.5 4.5L19 7.5" />);
export const IBan = mk(<><circle cx="12" cy="12" r="9" /><path d="m5.6 5.6 12.8 12.8" /></>);
export const IHelp = mk(<><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7v.5" /><path d="M12 17h.01" /></>);
export const IAlert = mk(<><path d="M12 3 2 20h20z" /><path d="M12 10v4M12 17h.01" /></>);
export const IInfo = mk(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>);
export const IBus = mk(<><rect x="5" y="3" width="14" height="15" rx="3" /><path d="M5 11h14M8 21v-3M16 21v-3" /><circle cx="8.5" cy="14.5" r=".8" /><circle cx="15.5" cy="14.5" r=".8" /></>);
export const IFlag = mk(<><path d="M5 21V4" /><path d="M5 4h11l-2 4 2 4H5" /></>);
export const IStar = mk(<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.5 2.9 1-6.1L3.2 9.5l6.1-.9z" />);
export const IExternal = mk(<><path d="M14 4h6v6" /><path d="M20 4 11 13" /><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" /></>);
export const IGlobe = mk(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>);
export const IMap = mk(<><path d="m9 4-6 2.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5z" /><path d="M9 4v13.5M15 6.5V20" /></>);
export const ITrash = mk(<><path d="M4 7h16M10 11v6M14 11v6" /><path d="M6 7l1 13h10l1-13M9 7V4h6v3" /></>);
export const IBuilding = mk(<><rect x="5" y="3" width="14" height="18" rx="1.5" /><path d="M9 7h.01M15 7h.01M9 11h.01M15 11h.01M9 15h.01M15 15h.01M10.5 21v-3h3v3" /></>);
export const ITrain = mk(<><rect x="6" y="3" width="12" height="13" rx="3" /><path d="M6 10h12M9 20l-2 2M15 20l2 2M9 13h.01M15 13h.01" /></>);

export function Logo({ size = 38 }: { size?: number }) {
  return (
    <svg className="brand-mark" width={size} height={size} viewBox="0 0 64 64" aria-hidden>
      <rect width="64" height="64" rx="18" fill="#101830" />
      <path d="M10 49h44" stroke="#ff5468" strokeWidth="4" strokeLinecap="round" strokeDasharray="0 0" opacity=".9" />
      <path d="M10 49h18" stroke="#2fd581" strokeWidth="4" strokeLinecap="round" />
      <path d="M32 9c-8 0-14.5 6.3-14.5 14.1 0 10.5 14.5 22.4 14.5 22.4s14.5-11.9 14.5-22.4C46.5 15.3 40 9 32 9z" fill="#2fd581" />
      <path d="M27.5 16.5h6a5.3 5.3 0 0 1 0 10.6h-2.3v5.4h-3.7z" fill="#101830" />
      <path d="M31.2 20.3h2.1a1.6 1.6 0 0 1 0 3.2h-2.1z" fill="#2fd581" />
    </svg>
  );
}
