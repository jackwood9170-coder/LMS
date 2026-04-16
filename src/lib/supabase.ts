import { createClient } from '@supabase/supabase-js'

// Public anon key — safe to embed (rate-limited by Supabase RLS)
const supabaseUrl = 'https://wycndcczlisnwmfxigrn.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Ind5Y25kY2N6bGlzbndtZnhpZ3JuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM2OTI3NTcsImV4cCI6MjA4OTI2ODc1N30.h5Ow6E2pkxcWa49d0gS3dqy6MHr-RmqW-3bd8_qwgfc'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
