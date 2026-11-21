'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ChevronDown, Menu, Moon, Sun, UserRound, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Brand } from './brand';
import { TOOLS } from '@/lib/tools';
import { buttonClass } from './ui/button';

export function Header() {
  const [dark, setDark] = useState(false);
  const [openMenu, setOpenMenu] = useState<'tools' | 'mobile' | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    setDark(document.documentElement.dataset.theme === 'dark');
  }, []);

  useEffect(() => { setOpenMenu(null); }, [pathname]);

  useEffect(() => {
    function close(event: KeyboardEvent) { if (event.key === 'Escape') setOpenMenu(null); }
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, []);

  function toggleTheme() {
    const theme = dark ? 'light' : 'dark';
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('pdf-pro-theme', theme); } catch { /* Theme still applies in this tab. */ }
    setDark(!dark);
  }

  return <header className="site-header">
    <div className="shell header-inner">
      <Brand />
      <nav className="desktop-nav" aria-label="Main navigation">
        <div className="tool-menu-wrap" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpenMenu(null); }}>
          <button className="nav-link nav-trigger" aria-expanded={openMenu === 'tools'} aria-controls="tool-navigation" onClick={() => setOpenMenu(openMenu === 'tools' ? null : 'tools')}>
            PDF Tools <ChevronDown size={14} aria-hidden="true" />
          </button>
          {openMenu === 'tools' && <div className="tool-menu" id="tool-navigation">
            {TOOLS.map(({ id, title, icon: Icon }) => <Link href={`/${id}`} key={id} onClick={() => setOpenMenu(null)}><Icon size={17} aria-hidden="true" />{title}</Link>)}
            <Link className="all-tools-menu" href="/tools" onClick={() => setOpenMenu(null)}>View all PDF tools</Link>
          </div>}
        </div>
        <Link className="nav-link" href="/pdf-to-word" aria-current={pathname === '/pdf-to-word' ? 'page' : undefined}>PDF to Word</Link>
        <Link className="nav-link" href="/pricing" aria-current={pathname === '/pricing' ? 'page' : undefined}>Pricing</Link>
      </nav>
      <div className="header-actions">
        <button className="icon-button theme-toggle" onClick={toggleTheme} aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}>
          {dark ? <Sun size={19} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
        </button>
        <Link className={buttonClass('outline', 'account-link')} href="/account"><UserRound size={16} aria-hidden="true" /> Account</Link>
        <button className="icon-button mobile-menu-toggle" onClick={() => setOpenMenu(openMenu === 'mobile' ? null : 'mobile')} aria-expanded={openMenu === 'mobile'} aria-controls="mobile-navigation" aria-label={openMenu === 'mobile' ? 'Close navigation' : 'Open navigation'}>
          {openMenu === 'mobile' ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
      </div>
    </div>
    {openMenu === 'mobile' && <nav className="mobile-nav shell" id="mobile-navigation" aria-label="Main navigation">
      <Link href="/" onClick={() => setOpenMenu(null)}>Home</Link><Link href="/tools" onClick={() => setOpenMenu(null)}>PDF Tools</Link>
      {TOOLS.slice(0, 6).map(({ id, title }) => <Link key={id} href={`/${id}`} onClick={() => setOpenMenu(null)}>{title}</Link>)}
      <Link href="/pricing" onClick={() => setOpenMenu(null)}>Pricing</Link><Link href="/account" onClick={() => setOpenMenu(null)}>Account</Link>
    </nav>}
  </header>;
}
