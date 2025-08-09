"use client";
import {
  Navbar,
  NavBody,
  NavItems,
  MobileNav,
  NavbarLogo,
  NavbarButton,
  MobileNavHeader,
  MobileNavToggle,
  MobileNavMenu,
} from "@/components/ui/resizable-navbar";
import { useState } from "react";
import { useUser } from "@auth0/nextjs-auth0/client";

export function NavbarDemo() {
const { user, isLoading } = useUser()
  const navItems = [
    {
        name: "Leaderboard",
        link: "/#leaderboard",
      },
    {
        name: "About",
        link: "/about",
      },
  ];
 
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
 
  return (
    <div className="relative w-full">
      <Navbar>
        {/* Desktop Navigation */}
        <NavBody>
          <NavbarLogo />
          <NavItems items={navItems} />
          <div className="flex items-center gap-4">
            {user ? <NavbarButton variant="secondary" onClick={() => {window.location.href = '/api/auth/logout'}}>Signout</NavbarButton> : <NavbarButton variant="secondary" onClick={() => {window.location.href = '/api/auth/login'}}>Sign In</NavbarButton>}
            {/* <NavbarButton variant="primary">Book a call</NavbarButton> */}
          </div>
        </NavBody>
 
        {/* Mobile Navigation */}
        <MobileNav>
          <MobileNavHeader>
            <NavbarLogo />
            <MobileNavToggle
              isOpen={isMobileMenuOpen}
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
            />
          </MobileNavHeader>
 
          <MobileNavMenu
            isOpen={isMobileMenuOpen}
            onClose={() => setIsMobileMenuOpen(false)}
          >
            {navItems.map((item, idx) => (
              <a
                key={`mobile-link-${idx}`}
                href={item.link}
                onClick={() => setIsMobileMenuOpen(false)}
                className="relative text-neutral-600 dark:text-neutral-300"
              >
                <span className="block">{item.name}</span>
              </a>
            ))}
            <div className="flex w-full flex-col gap-4">
              {user ? (<NavbarButton
                onClick={() => setIsMobileMenuOpen(false)}
                variant="primary"
                className="w-full"
              >
                {user.name}
              </NavbarButton>):(<NavbarButton
                onClick={() => setIsMobileMenuOpen(false)}
                variant="primary"
                className="w-full"
              >
                Sign In
              </NavbarButton>)}
              {/* <NavbarButton
                onClick={() => {setIsMobileMenuOpen(false); window.location.href = '/api/auth/login'}}
                variant="primary"
                className="w-full"
              >
                Book a call
              </NavbarButton> */}
            </div>
          </MobileNavMenu>
        </MobileNav>
      </Navbar>
    </div>
  );
}