import { getSession } from '@auth0/nextjs-auth0';
import GameInterfaceComponent from '@/components/GameInterface';

export default async function PlayPage() {
  const session = await getSession();
  
  const user = session ? {
    id: session.user.sub,
    email: session.user.email,
    name: session.user.name,
    picture: session.user.picture,
    accessToken: session.accessToken as string
  } : null;

  return <GameInterfaceComponent user={user} />;
}