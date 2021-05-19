#!/usr/bin/env python

'''
DESCRIPTION
-----------
    Traning proposed neural network
    
USAGE
-----
    [PROJECT_PATH]/$ python notebooks/04-pg-model-training.py -design                   {DESIGN NAME}
                                                              -first_hidden_layer_pbk   {BIOLOGICAL KNOWLEDGE}
                                                              -first_hidden_layer_dense {NUMBER of DENSE LAYER}
                                                              -second_hidden_layer      {SECOND HIDDEN LAYER}
                                                              -optimizer                {OPTIMIZER}
                                                              -activation               {ACTIVATION}
                                                              -ds                       {DATASET PATH}
                                                              -analysis                 {THE NAME of ANALYSIS}
                                                              -filtering_gene_space     {GENE SPACE FILTERING}
RETURN
------
    {MODEL}.h5 : h5 file
        Trained model
    {MODEL-RESULT}.csv : csv file
        The model result with probabilities, prediction label and ground truth

EXPORTED FILE(s) LOCATION
-------------------------
    ./models/NN/{EXPERIMENT}/{MODEL}.h5
    ./models/NN/{EXPERIMENT}/{MODEL-RESULT}.csv
'''

SEED = 91 # for reproducible result
import os, argparse, sys
sys.path.append('./')
# importing scripts in scripts folder
from scripts import config as src

# to get reproducible results
import tensorflow as tf
tf.random.set_seed(SEED)
import numpy as np
np.random.seed(SEED)
os.environ["TF_DETERMINISTIC_OPS"] = "1"

import pandas as pd
import datetime as dt

from sklearn.preprocessing import OneHotEncoder
from sklearn.cluster import KMeans

from numba import cuda
from tensorflow import keras

pd.set_option('display.max_columns', 7)

def NN_training_testing(design_name, bio_knowledge, dense_nodes, second_hidden_layer, optimizer, activation, dataset_path, analysis, filtering_gene_space):
    try:
        # VALUES for split operation
        test_size = 0.3            # For train_test_split, the size of testing sample
        n_p_leave_out = [2,4,6,8]  # For LeavePGroupsOut split, the celltype number which will randomly leave out from dataset  # [2,4,6,8]
        p_out_iteration = 20        # For LeavePGroupsOut split, the iteration number for randomly leaving-out cell types        # 20
        stratified_split = 10      # For StratifiedKFold and RepeatedStratifiedKFold, the split number                          # 10
        stratified_repeat = 50     # For RepeatedStratifiedKFold, the number of iteration                                       # 50
        
        # VALUES for neuran network
        epochs_default = 100       # the number of epoch
        batch_default = 10         # the size of batch
        val_split = 0.1            # the percentage of validation split
        
        df_result = pd.DataFrame() # the metric scores for given analysis
        how_join='left' # if the network needs to filter the gene space this features updating in below
        
#         defining split operaiton according to analysis
        if analysis == 'clustering':
            split = 'LeavePGroupsOut'
        elif analysis == 'encoding':
            split = 'train_test_split'
        elif analysis == 'retrieval_lof':
            split = 'LeaveOneGroupOut'
        elif analysis == 'evaluate_skf':
            split = 'StratifiedKFold'
        elif analysis == 'evaluate_rskf':
            split = 'RepeatedStratifiedKFold'
        elif analysis == 'retrieval':
            split = 'None'
        else:
            raise Exception (f'INVALID analysis value!! -- {analysis}')
        
#         splitting string, will use during naming the files
        experiment_name = dataset_path.split('/')[1]
        dataset_name = dataset_path.split('/')[-1].split('.')[0]

#         defining the location for outputs of results and models
        loc_output_models = os.path.join(src.DIR_MODELS, experiment_name, split)
        src.define_folder(loc_=loc_output_models)
####         ./models/{ANALYSIS}/{EXPERIMENT}/{SPLIT}/{THE_TRAINED_MODEL_for_SELECTED_DESING}.h5
        loc_output_reports_analysis = os.path.join(src.DIR_REPORTS, analysis, experiment_name)
        src.define_folder(loc_=loc_output_reports_analysis)
####         ./reports/{ANALYSIS}/{EXPERIMENT}/{SPLIT}/{THE_RESULT_or_METRICS_for_SELECTED_DESING}.csv
        loc_output_print = os.path.join(src.DIR_NOHUP, experiment_name)
        src.define_folder(loc_=loc_output_print)
####         ./nohup/{EXPERIMENT}/info_{SPLIT}.txt
        
#         During the execution of this notebook, some informations, related with the experiment, dataset or network design, will exported into txt file.
        file_operation = 'w+' # create the txt file is not exist or re-write into txt file
        export_to_txt = src.Export_to_text(experiment=experiment_name
                                            , detail=analysis+'_'+design_name
                                            , loc=loc_output_print)
    
        time_start = dt.datetime.now().time().strftime('%H:%M:%S') # = time.time() dt.datetime.now().strftime('%Y%m%d_%I%M%S%p')
#         adding information
        export_to_txt.save(text=f'Script execution start time, {time_start}', file_operation=file_operation)
        export_to_txt.save(text='****SCRIPT INFORMATION****')
        export_to_txt.save(text=f'design_name: {design_name}\n bio_knowledge: {bio_knowledge}\n dense_nodes: {dense_nodes}\n second_hidden_layer: {second_hidden_layer}\n optimizer: {optimizer}\n dataset: {dataset_name}\n split: {split}\n filter_gene_space: {filtering_gene_space}')

        if filtering_gene_space==True and bio_knowledge!=None:
            export_to_txt.save(text='INFO, Design is fully connected. Not filtered the gene space, all the genes are using!!')

#         Reading dataset
        df = pd.read_pickle(os.path.join(src.DIR_DATA, dataset_path))  
        cell_type_info = df.groupby('cell_type').size().index.values

#         Creating dense layer in regards to given number of nodes via dense_nodes. If there is no included
#         dense layer, then an empty dataframe is creating.
        if  dense_nodes == 0:
            df_dense = pd.DataFrame()
        else:
            print('***** DENSE LAYER ADDED - {}!!'.format(dense_nodes))
            gene_name = df.columns[:-1]
            col_name = ['dense_'+str(i+1) for i in range(dense_nodes)]
            df_dense = pd.DataFrame(np.ones([len(gene_name),dense_nodes]), index=gene_name, columns=col_name)
                
#         Importing prior biological knowledge(pbk), if it defined as None, an empty dataframe is creating.
#         If not, the information is reading from given location via bio_knowledge. 
#         in addition, if network wants to design as filtering gene space according to pbk then the filtering
#         gene space steps is applying in following step. 
        if (bio_knowledge == 'None'):
            df_bio = pd.DataFrame()
        else:
            df_bio = pd.DataFrame(pd.read_csv(os.path.join(src.DIR_DATA_PROCESSED, bio_knowledge), index_col=0))
            export_to_txt.save(f'Prior biological knowledge imported!, shape {df_bio.shape}')

            if  filtering_gene_space==True:
                export_to_txt.save(text='***** GENE SPACE FILTERED!!')
                how_join = 'right'

#         Merging biological and dense layer to use in first hidden layer
        df_bio_with_df = pd.merge(left=pd.DataFrame(df.columns[:-1]).set_index(0)
                                         , right=df_bio
                                         , left_index=True
                                         , right_index=True
                                         , how=how_join).fillna(0.0)

        df_first_hidden_layer = pd.merge(left=df_bio_with_df
                                         , right=df_dense
                                         , left_index=True
                                         , right_index=True
                                         , how='left').fillna(0.0)
#         adding information
        export_to_txt.save(text='********** DATAFRAME DETAILS **********')
        export_to_txt.save(text=f'Dataset cell type, {cell_type_info}\nDataset shape, {df.shape}\nhead(5)\n{df.head()}')
        export_to_txt.save(text='********** FIRST HIDDEN LAYER DETAILS **********')
        export_to_txt.save(text=f'First hidden layer shape, {df_first_hidden_layer.shape}\nhead(5)\n{df_first_hidden_layer.head()}')

#         Defining feature and target columns
        ohe = OneHotEncoder()
        X = df.iloc[:, :-1].values
        y = df.iloc[:, -1:].values
        y_category = df.iloc[:, -1].astype('category').cat.codes
        y_ohe = ohe.fit_transform(y).toarray()
        groups = df.iloc[:, -1].values
        
#         adding information
        export_to_txt.save(text='********** FEATURE and TARGET COLUMNS **********')
        export_to_txt.save(text=f'X shape, {X.shape}\ny shape, {y.shape}')

        START_TRAINING = dt.datetime.now().time().strftime('%H:%M:%S')

#         NN callback definition, in training step, the traning will stop if the 'monitor' feauture is less than 'min_delta' value 
#         for 'patience' times in a row.
        callbacks = [keras.callbacks.EarlyStopping(monitor="val_loss" # Stop training when `val_loss` is no longer improving
                                               , min_delta=1e-5   # "no longer improving" being defined as "no better than 1e-5 less"
                                               , patience=3       # "no longer improving" being further defined as "for at least 3 epochs"
                                               , verbose=1 ) ]

        export_to_txt.save(text='********** "SPLIT" DETAILS **********')
        X_train_list, y_train_list, X_test_list, y_test_list, split_index_list, co_list = src.generate_training_testing_samples(X, y, y_ohe, y_category, groups, SEED
                                                                                                                              , split
                                                                                                                              , stratified_split, stratified_repeat
                                                                                                                              , n_p_leave_out, p_out_iteration
                                                                                                                              , test_size
                                                                                                                              , export_to_txt)
        
#         Model creating and fitting steps
        for i in range(len(X_train_list)):
            print(f'{i+1}/{len(X_train_list)} -- {dt.datetime.now().time().strftime("%H:%M:%S")}')
            export_to_txt.save(text = f'{i+1}/{len(X_train_list)} -- {dt.datetime.now().time().strftime("%H:%M:%S")}')
            keras.backend.clear_session()
            model = src.proposed_NN(X=X, y=y
                            , bio_layer=df_first_hidden_layer
                            , select_optimizer=optimizer
                            , select_activation=activation
                            , second_layer=second_hidden_layer)
            model.fit(X_train_list[i], y_train_list[i]
                      , epochs=epochs_default
                      , batch_size=batch_default
                      , verbose=1
                      , callbacks=callbacks
                      , validation_split=val_split)
            
#             obtaining encoding part from model
            model_encoding = tf.keras.models.Model(inputs=model.layers[0].input
                                                   , outputs=model.layers[-1].input)
            
            
#             Saving fitted model
            if analysis == 'retrieval' or analysis == 'retrieval_lof':
                export_to_txt.save(text='********** MODEL IS SAVING **********')
                export_to_txt.save(text=f'Model is saving for split --> {split} !!')
                model.save(os.path.join(loc_output_models, f'design_{design_name}_{dataset_name}_{optimizer}_{activation}_{i}.h5'))
                export_to_txt.save(text=f"{os.path.join(loc_output_models, f'design_{design_name}_{dataset_name}_{optimizer}_{activation}_{i}.h5')}")
                
            elif analysis == 'encoding':
                export_to_txt.save(text='********** MODEL IS SAVING **********')
                export_to_txt.save(text=f'Model(encoding) is saving for split --> {split} !!')
                model_encoding.save(os.path.join(loc_output_models, f'encoding_{design_name}_{dataset_name}_{optimizer}_{activation}.h5'))
                export_to_txt.save(text=f"{os.path.join(loc_output_models, f'encoding_{design_name}_{dataset_name}_{optimizer}_{activation}.h5')}")

            else: 
#                 clustering analysis executing
                if analysis == 'clustering':
#                     getting encoding part for testing sample
                    encoding_testing = model_encoding.predict(X_test_list[i])
#                     clustering prediction
                    kmeans = KMeans(n_clusters=co_list[i], random_state=SEED).fit(encoding_testing)
                    y_pred = kmeans.predict(encoding_testing)

                    df_split = pd.DataFrame(y_pred, columns=['prediction'])
                    df_split['ground_truth'] = y_test_list[i].values
                    df_split['cell_out']='cell_out_'+str(co_list[i])

                else:
#                     model cell type prediction
                    y_pred = model.predict(X_test_list[i])
#                     df_split = src.generate_pred_result(y_pred, y_test_list[i], ohe)
                    df_split = pd.DataFrame(y_pred, columns=list(pd.DataFrame(ohe.categories_).iloc[0,:]))
                    df_split['prediction'] = ohe.inverse_transform(y_pred).reshape(1, -1)[0]
                    df_split['ground_truth'] = ohe.inverse_transform(y_test_list[i]).reshape(1, -1)[0]

                df_split['index_split'] = str(split_index_list[i])
                df_split['design']=design_name
                df_result = pd.concat([df_result, df_split])

#         exporting model summary into txt file(for information purpose)
        stringlist = []
        
        
        if analysis=='encoding' or analysis=='clustering':
            model_encoding.summary(print_fn=lambda x: stringlist.append(x))
            text_summary = 'Model(encoding) summary ;'
        else:
            model.summary(print_fn=lambda x: stringlist.append(x))
            text_summary = 'Model summary ;'
        
        short_model_summary = '\n'.join(stringlist)
        export_to_txt.save(text=f'********** MODEL DETAILS ********** \n\n{text_summary} {short_model_summary}')
        print(f'********** MODEL DETAILS ********** \n\n{text_summary} {short_model_summary}')

        if len(df_result) > 0:
#             exporting the result for all iterations
            df_result.to_csv(os.path.join(loc_output_reports_analysis,f'detail_{design_name}_{dataset_name}_{optimizer}_{activation}.csv'), index=False)
            export_to_txt.save(text=f"{os.path.join(loc_output_reports_analysis,f'detail_{design_name}_{dataset_name}_{optimizer}_{activation}.csv')}")
        

#         calculating metric scores
        if analysis == 'clustering':
            df_metric = src.calculate_clustering_metrics(df_result)
            df_metric['design'] = design_name
            df_mean = df_metric.groupby(['design'
                                     ,'metric'
                                     ,'cell_out']).mean().reset_index().pivot(index=['design'
                                                                                     ,'cell_out']
                                                                              , columns='metric', values='score')
            df_mean.to_csv(os.path.join(loc_output_reports_analysis, 'metrics_'+design_name+'.csv'))
            export_to_txt.save(text=f'clustering metrics saved into {loc_output_reports_analysis}')
            print(f'clustering metrics saved into {loc_output_reports_analysis}')
            
        if analysis =='evaluate_skf' or analysis=='evaluate_rskf':
            df_metric_overall = src.calculate_f1_recall_precision_metrics_overall(df_result)
            df_metric_overall['design'] = design_name
            df_metric_overall.to_csv(os.path.join(loc_output_reports_analysis, 'metrics_overall_'+design_name+'.csv'), index=False)
            df_metric_detail = src.calculate_f1_recall_precision_metrics_cell_type_detail(df_result)
            df_metric_detail['design'] = design_name
            df_metric_detail.to_csv(os.path.join(loc_output_reports_analysis, 'metrics_detail_'+design_name+'.csv'), index=False)
            export_to_txt.save(text=f'F1-precision-recall metrics saved into {loc_output_reports_analysis}')
            print(f'F1-precision-recall metrics saved into {loc_output_reports_analysis}')

    
        if analysis == 'retrieval':
            src.retrieval.main(model_encoding, 0, 'saved_model', 0, 'all', design_name)

        time_end = dt.datetime.now().time().strftime('%H:%M:%S')
        export_to_txt.save(text=f'Script execution finish time, {time_end}')
    
    
    except:
        print("Unexpected error:", sys.exc_info()[0])
            
if __name__=='__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument('-design'                  , '--design_name', help='name of design')
    parser.add_argument('-first_hidden_layer_pbk'  , '--bio_knowledge', help='integrated prior biologicl knowledge')
    parser.add_argument('-first_hidden_layer_dense', '--dense_nodes', help='integrated dense node into first hidden layer')
    parser.add_argument('-second_hidden_layer'     , '--second_hidden_layer', help='second layer exist or not')
    parser.add_argument('-optimizer'               , '--optimizer', help='selecting the optimizer')
    parser.add_argument('-activation'              , '--activation', help='selecting the actibation')
    parser.add_argument('-ds'                      , '--dataset_path', help='the path of dataset')
    parser.add_argument('-analysis'                , '--analysis', help='the name of the analysis')
    parser.add_argument('-filter_gene_space'       , '--filter_space', help='filtering gene space with given bio knowledge set')
    
    
    if len(sys.argv)==1:
        parser.print_help(sys.stderr)
        sys.exit(1)
        
    args = parser.parse_args()
    NN_training_testing(args.design_name
                        , args.bio_knowledge
                        , int(args.dense_nodes)
                        , eval(args.second_hidden_layer)
                        , args.optimizer
                        , args.activation
                        , args.dataset_path
                        , args.analysis
                        , eval(args.filter_space)
                        )
    