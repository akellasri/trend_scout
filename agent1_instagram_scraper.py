# ==============================================================================
#  STEP 0: INSTALL LIBRARIES
# ==============================================================================
!pip install apify-client openai -q
 
import os
import json
from apify_client import ApifyClient
from openai import AzureOpenAI
from google.colab import userdata
 
# ==============================================================================
#  PART 1: SCRAPING FUNCTION (WITH DATE FILTER)
# ==============================================================================
def scrape_instagram_data(client, target_usernames, date_filter):
    """
    Scrapes Instagram posts newer than a specific date for maximum reliability.
    """
    output_file = "instagram_posts_scraped.json"
 
    # --- FINAL, RELIABLE ACTOR INPUT ---
    actor_input = {
        "username": target_usernames,
        # THE FIX: This parameter filters posts directly on the server.
        "onlyPostsNewerThan": date_filter,
        "shouldCollectComments": False,
        # As per the docs, this helps correctly filter older pinned posts.
        "skipPinnedPosts": True
    }
 
    actor_name = "apify/instagram-post-scraper"
    print(f"-> Starting Actor '{actor_name}' to get posts newer than '{date_filter}'...")
    try:
        actor_run = client.actor(actor_name).call(run_input=actor_input)
        print("-> Fetching results from the dataset...")
        final_results = []
        for item in client.dataset(actor_run["defaultDatasetId"]).iterate_items():
            cleaned_post = {
                "page_url": f"https://www.instagram.com/{item.get('ownerUsername', '')}/",
                "post_url": item.get('url', ''),
                "image_url": item.get('displayUrl', ''),
                "caption_text": item.get('caption', ''),
                "extracted_hashtags": item.get('hashtags', []),
                "post_timestamp": item.get('timestamp', ''),
                "like_count": item.get('likesCount', 0),
                "comment_count": item.get('commentsCount', 0)
            }
            final_results.append(cleaned_post)
 
        if not final_results:
            return None
 
        print(f"-> Saving {len(final_results)} scraped posts to '{output_file}'...")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(final_results, f, indent=4, ensure_ascii=False)
        return output_file
 
    except Exception as e:
        print(f"-> An error occurred during scraping: {e}")
        return None
 
# ==============================================================================
#  PART 2: AI ENRICHMENT USING AZURE OPENAI (No Changes)
# ==============================================================================
def enrich_data_with_azure_vision_ai(client, deployment_name, input_filename):
    """
    Reads a JSON file and uses Azure OpenAI vision to analyze each post.
    """
    output_file = "instagram_posts_enriched_azure.json"
 
    print(f"-> Reading data from '{input_filename}'...")
    with open(input_filename, 'r', encoding='utf-8') as f:
        posts = json.load(f)
 
    for post in posts:
        caption = post.get("caption_text", "")
        image_url = post.get("image_url", "")
 
        if not image_url:
            post["fashion_analysis"] = {"error": "No image URL found."}
            continue
 
        print(f"-> Analyzing image and caption for post: {post['post_url']}")
        try:
            prompt_text = """
            You are a fashion expert. Analyze the provided image and caption.
            Respond ONLY with a valid JSON object with the following keys:
            - "image_description": A detailed, one-sentence description of the main fashion item(s) worn.
            - "colors": List of specific colors from the item(s).
            - "fabrics": List of fabrics you can identify.
            - "prints_patterns": List of prints or patterns.
            - "garment_type": The type of clothing.
            - "style_fit": The fit or style.
            If an attribute is not identifiable, provide an empty list [].
            """
            response = client.chat.completions.create(
                model=deployment_name,
                messages=[
                    { "role": "user", "content": [ {"type": "text", "text": prompt_text}, {"type": "image_url", "image_url": {"url": image_url}} ], }
                ],
                response_format={"type": "json_object"},
                max_tokens=500
            )
            attributes = json.loads(response.choices[0].message.content)
            post["fashion_analysis"] = attributes
        except Exception as e:
            print(f"-> Could not enrich post with Azure vision. Error: {e}")
            post["fashion_analysis"] = {"error": str(e)}
 
    print(f"-> Saving enriched data to '{output_file}'...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(posts, f, indent=4, ensure_ascii=False)
    return output_file
 
# ==============================================================================
#  PART 3: MAIN AUTOMATION SCRIPT
# ==============================================================================
def run_full_pipeline_azure():
    """
    Executes the entire automated pipeline using Apify and Azure OpenAI.
    """
    try:
        apify_client = ApifyClient(userdata.get('APIFY_TOKEN'))
        azure_deployment_name = userdata.get('AZURE_OPENAI_DEPLOYMENT_NAME')
        azure_openai_client = AzureOpenAI(
            azure_endpoint=userdata.get('AZURE_OPENAI_ENDPOINT'),
            api_key=userdata.get('AZURE_OPENAI_API_KEY'),
            api_version="2024-05-01-preview"
        )
        print("✅ All secrets loaded and clients initialized.")
    except Exception as e:
        print(f"❌ Failed to load secrets or initialize clients. Error: {e}")
        return
 
    # --- Configuration ---
    target_profiles = ["pichori.in", "kalkifashion"]
    # You can change this to "1 month", "2 weeks", "2024-08-01", etc.
    scrape_period = "7 days"
 
    print("\n--- STEP 1: SCRAPING INSTAGRAM DATA ---")
    scraped_file = scrape_instagram_data(apify_client, target_profiles, scrape_period)
 
    if scraped_file:
        print("\n--- STEP 2: ENRICHING DATA WITH AZURE AI VISION ---")
        enriched_file = enrich_data_with_azure_vision_ai(azure_openai_client, azure_deployment_name, scraped_file)
        print(f"\n🎉🎉🎉 AUTOMATION COMPLETE! 🎉🎉🎉")
        print(f"Final enriched data is in the file: {enriched_file}")
    else:
        print("\n❌ Automation stopped because the scraping step failed or found no new posts.")
 
# --- RUN THE AUTOMATION ---
run_full_pipeline_azure()