import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { UserProvider } from '@auth0/nextjs-auth0/client';
import Footer from '@/components/Footer';
import { NavbarDemo } from '@/components/NavBarDemo'

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Dilemma Bench",
  description: "A benchmark for evaluating LLMs through language-based social dilemmas",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-gray-50 min-h-screen`}
      >
        <UserProvider>
          <div className="flex flex-col min-h-screen">
          <NavbarDemo /> 
            <main className="flex-1 mt-8">
              {children}
            </main>
            <Footer />
          </div>
        </UserProvider>
      </body>
    </html>
  );
}
