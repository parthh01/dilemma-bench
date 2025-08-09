import { getSession } from '@auth0/nextjs-auth0';
import ProfilePageComponent from '@/components/ProfilePage';

interface UserPageProps {
  params: {
    id: string;
  };
}

export default async function UserPage({ params }: UserPageProps) {
  const session = await getSession();
  
  const user = session ? {
    id: session.user.sub,
    email: session.user.email,
    name: session.user.name,
    picture: session.user.picture,
    accessToken: session.accessToken as string
  } : null;

  return <ProfilePageComponent profileId={params.id} profileType="user" user={user} />;
}