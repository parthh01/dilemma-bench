import { getSession } from '@auth0/nextjs-auth0';
import ProfilePageComponent from '@/components/ProfilePage';

interface AgentPageProps {
  params: {
    id: string;
  };
}

export default async function AgentPage({ params }: AgentPageProps) {
  const session = await getSession();
  
  const user = session ? {
    id: session.user.sub,
    email: session.user.email,
    name: session.user.name,
    picture: session.user.picture,
    accessToken: session.accessToken as string
  } : null;

  return <ProfilePageComponent profileId={params.id} profileType="agent" user={user} />;
}