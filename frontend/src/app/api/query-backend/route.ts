import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL;
const API_KEY = process.env.BACKEND_UI_SECRET;

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const endpoint = searchParams.get('endpoint');
  
  if (!endpoint) {
    return NextResponse.json({ error: 'Missing endpoint parameter' }, { status: 400 });
  }

  if (!API_KEY) {
    return NextResponse.json({ error: 'API key not configured' }, { status: 500 });
  }

  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'Backend URL not configured' }, { status: 500 });
  }

  try {
    const backendUrl = `${BACKEND_URL}${endpoint}`;
    
    // Check for user authentication in headers
    const authHeader = request.headers.get('authorization');
    
    const headers: Record<string, string> = {
      'X-API-Key': API_KEY,
      'Content-Type': 'application/json',
    };
    
    // Add Bearer token if provided
    if (authHeader && authHeader.startsWith('Bearer ')) {
      headers['Authorization'] = authHeader;
    }
    
    const response = await fetch(backendUrl, {
      method: 'GET',
      headers,
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend request failed: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Backend request error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch from backend' },
      { status: 500 }
    );
  }
}

export async function POST(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const endpoint = searchParams.get('endpoint');
  
  if (!endpoint) {
    return NextResponse.json({ error: 'Missing endpoint parameter' }, { status: 400 });
  }

  if (!API_KEY) {
    return NextResponse.json({ error: 'API key not configured' }, { status: 500 });
  }

  if (!BACKEND_URL) {
    return NextResponse.json({ error: 'Backend URL not configured' }, { status: 500 });
  }

  try {
    const backendUrl = `${BACKEND_URL}${endpoint}`;
    
    // Check for user authentication in headers
    const authHeader = request.headers.get('authorization');
    
    // Handle different content types
    const contentType = request.headers.get('content-type');
    let body;
    let headers: Record<string, string> = {
      'X-API-Key': API_KEY,
    };
    
    // Add Bearer token if provided
    if (authHeader && authHeader.startsWith('Bearer ')) {
      headers['Authorization'] = authHeader;
    }

    if (contentType?.includes('application/json')) {
      body = await request.json();
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    } else if (contentType?.includes('multipart/form-data')) {
      // For file uploads, pass the FormData directly
      body = await request.formData();
      // Don't set Content-Type for FormData, let fetch handle it
    } else {
      body = await request.text();
      if (contentType) {
        headers['Content-Type'] = contentType;
      }
    }

    const response = await fetch(backendUrl, {
      method: 'POST',
      headers,
      body,
    });

    if (!response.ok) {
      return NextResponse.json(
        { error: `Backend request failed: ${response.status}` },
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Backend request error:', error);
    return NextResponse.json(
      { error: 'Failed to fetch from backend' },
      { status: 500 }
    );
  }
}
