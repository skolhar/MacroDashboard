import './globals.css';
import './phase2.css';
export const metadata = { title: 'India Macro Reflexivity | DEMO', description: 'Synthetic demonstration dashboard for macro risk research' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
