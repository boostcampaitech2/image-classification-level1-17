python ../train.py \
         --epochs 10 \
         --dataset MaskSplitStratifyDataset \
         --label mask\
         --augmentation get_transforms \
         --resize 384 384 \
         --lr 0.00003 \
         --lr_decay_step 50 \
         --lr_gamma 0.5 \
         --batch_size 16 \
         --valid_batch_size 32 \
         --model EfficientNet \
         --model_version tf_efficientnet_b7\
         --optimizer Adam \
         --criterion focal\
         --log_interval 100\
<<<<<<< HEAD:baseline/train_effnet.sh
         --name T2065/EfficientNet_b7_0902_mask
=======
         --name EfficientNet_b3_pruned_0831
>>>>>>> refactor:sh/train_effnet.sh
         
python train.py \
         --epochs 10 \
         --dataset MaskSplitStratifyDataset \
         --label gender\
         --augmentation get_transforms \
         --resize 384 384 \
         --lr 0.00003 \
         --lr_decay_step 50 \
         --lr_gamma 0.5 \
         --batch_size 16 \
         --valid_batch_size 32 \
         --model EfficientNet \
         --model_version tf_efficientnet_b7\
         --optimizer Adam \
         --criterion focal\
         --log_interval 100\
         --name T2065/EfficientNet_b7_0902_gender

python train.py \
         --epochs 10 \
         --dataset MaskSplitStratifyDataset \
         --label age\
         --augmentation get_transforms \
         --resize 384 384 \
         --lr 0.00003 \
         --lr_decay_step 50 \
         --lr_gamma 0.5 \
         --batch_size 16 \
         --valid_batch_size 32 \
         --model EfficientNet \
         --model_version tf_efficientnet_b7\
         --optimizer Adam \
         --criterion focal\
         --log_interval 100\
         --name T2065/EfficientNet_b7_0902_age