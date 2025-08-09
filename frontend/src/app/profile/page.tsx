import { getSession } from '@auth0/nextjs-auth0';
import { redirect } from 'next/navigation';
import ProfilePageComponent from '@/components/ProfilePage';

export default async function MyProfilePage() {
  const session = await getSession();
  
  if (!session) {
    redirect('/api/auth/login');
  }

  const user = {
    id: session.user.sub,
    email: session.user.email,
    name: session.user.name,
    picture: session.user.picture,
    accessToken: session.accessToken as string
  };

  return <ProfilePageComponent profileId={user.id} profileType="user" user={user} />;
}