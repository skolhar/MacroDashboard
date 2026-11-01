import './globals.css';
import './phase2.css';
export const metadata = { title: 'SmartHedge | Macro Research', description: 'Macro reflexivity and source-status research dashboard; demonstration and research modes are labelled in the interface' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
